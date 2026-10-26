let cached: boolean | undefined;

/**
 * Whether this browser can give us a WebGL context.
 *
 * Memoised because the probe itself allocates a context, and browsers cap how
 * many can exist at once (~16 in Chrome). The probe context is released
 * immediately so it never counts against that ceiling.
 */
export function isWebGLAvailable(): boolean {
  if (cached !== undefined) return cached;
  if (typeof document === 'undefined') return (cached = false);

  try {
    const canvas = document.createElement('canvas');
    const gl = (canvas.getContext('webgl2') ??
      canvas.getContext('webgl') ??
      canvas.getContext('experimental-webgl')) as WebGLRenderingContext | null;

    if (!gl) return (cached = false);
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return (cached = true);
  } catch {
    return (cached = false);
  }
}
