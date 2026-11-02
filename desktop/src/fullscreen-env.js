// Fullscreen presentation uses a logical canvas separate from persisted board geometry.
export function fullscreenEnv(width, height) {
  const px = (value) => Math.max(1, Math.round(Number.isFinite(Number(value)) ? Number(value) : 1));
  return {
    size: { w: 24, h: 16, label: 'fullscreen' },
    pixel: { width: px(width), height: px(height) },
  };
}
