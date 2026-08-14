export default function MeshViewToggles({ wireframe, onWireframeChange, textureEnabled, onTextureChange, textureDisabled }) {
  return (
    <div className="toggle-row">
      <label className="checkbox">
        <input type="checkbox" checked={wireframe} onChange={(e) => onWireframeChange(e.target.checked)} />
        wireframe
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={textureEnabled}
          disabled={textureDisabled}
          onChange={(e) => onTextureChange(e.target.checked)}
        />
        texture
      </label>
    </div>
  );
}
