// a real file download (not a new tab/window) for a blob: URL - handing one
// to window.open doesn't reliably render or save anywhere: a real browser
// tab often just shows it inline with no way to save it, and the desktop
// app's pywebview/WebView2 window doesn't treat window.open specially at
// all - it hands the blob: URL to the OS's own "what app opens this"
// resolver, which has nothing registered for it ("get an app to open this
// blob link"). an anchor with a download attribute is what actually
// triggers the browser's/WebView2's own save-a-file flow in both cases.
export function triggerDownload(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
