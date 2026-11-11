// renders the morph export one frame at a time and encodes it with
// WebCodecs, every frame stamped at exactly i / fps - so the clip plays
// at an even 30 fps whatever the machine is doing meanwhile. recording the
// live canvas with MediaRecorder (the older path, still the fallback - see
// MorphControl.jsx) stamps frames with the wall clock instead: whenever the
// encoder or the page stalls for a moment, nothing gets captured and the
// clip shows a frozen frame followed by a jump, most often right at the
// start, and on a busy machine it only gets 14-20 fps to begin with.
import { ArrayBufferTarget, Muxer } from "mp4-muxer";

// H.264 High, Main, then High at a higher level for big frames - tried in
// order, the first one the engine says it can encode at this size wins.
const CODECS = ["avc1.640028", "avc1.4d0028", "avc1.640033"];

export function canEncodeFrames() {
  return typeof VideoEncoder !== "undefined" && typeof VideoFrame !== "undefined";
}

// the same t-curve MorphControl.jsx's live sweep follows: 0 -> 1 in
// secondsPerLeg (and back to 0 again unless forwardOnly), one t per frame,
// both ends included.
export function sweepTimes(secondsPerLeg, forwardOnly, fps) {
  const totalSeconds = forwardOnly ? secondsPerLeg : secondsPerLeg * 2;
  const frames = Math.max(1, Math.round(totalSeconds * fps));
  const times = [];
  for (let i = 0; i <= frames; i++) {
    const elapsed = (i / frames) * totalSeconds;
    const t = forwardOnly || elapsed <= secondsPerLeg ? elapsed / secondsPerLeg : 1 - (elapsed - secondsPerLeg) / secondsPerLeg;
    times.push(Math.max(0, Math.min(1, t)));
  }
  return times;
}

async function pickCodec(width, height, fps, bitrate) {
  for (const codec of CODECS) {
    const config = { codec, width, height, bitrate, framerate: fps, avc: { format: "avc" } };
    try {
      const { supported } = await VideoEncoder.isConfigSupported(config);
      if (supported) return config;
    } catch {
      // malformed for this engine - try the next one
    }
  }
  throw new Error(`no H.264 encoder available for ${width} x ${height}`);
}

const nextTask = () => new Promise((resolve) => setTimeout(resolve, 0));

// source: the WebGL canvas. drawFrame(t) must render t into it synchronously -
// the pixels are copied out right after, in the same task, before the
// browser gets a chance to clear the drawing buffer. width/height are
// rounded down to even numbers (H.264 needs that); the copy just drops the
// odd last row/column.
export async function encodeFrames({ source, times, drawFrame, fps = 30, bitrate = 12_000_000, onProgress }) {
  const width = source.width - (source.width % 2);
  const height = source.height - (source.height % 2);
  const config = await pickCodec(width, height, fps, bitrate);

  const copy = document.createElement("canvas");
  copy.width = width;
  copy.height = height;
  const ctx = copy.getContext("2d");

  const target = new ArrayBufferTarget();
  const muxer = new Muxer({ target, video: { codec: "avc", width, height, frameRate: fps }, fastStart: "in-memory" });
  let failure = null;
  const encoder = new VideoEncoder({
    output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
    error: (err) => {
      failure = err;
    },
  });
  encoder.configure(config);

  const frameMicros = 1e6 / fps;
  try {
    for (let i = 0; i < times.length; i++) {
      if (failure) throw failure;
      drawFrame(times[i]);
      ctx.drawImage(source, 0, 0);
      const frame = new VideoFrame(copy, { timestamp: Math.round(i * frameMicros), duration: Math.round(frameMicros) });
      encoder.encode(frame, { keyFrame: i % (fps * 2) === 0 });
      frame.close();
      onProgress?.((i + 1) / times.length);
      // keep the UI responsive, and don't run ahead of the encoder
      await nextTask();
      while (encoder.encodeQueueSize > 4 && !failure) await new Promise((resolve) => setTimeout(resolve, 5));
    }
    await encoder.flush();
    if (failure) throw failure;
  } finally {
    if (encoder.state !== "closed") encoder.close();
  }
  muxer.finalize();
  return new Blob([target.buffer], { type: "video/mp4" });
}
