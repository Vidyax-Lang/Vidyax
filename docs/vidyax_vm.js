/* pyodide-bridge.js
 * Compile Vidyax source (.vx) -> bytecode (.vxc bytes) in-browser via
 * Pyodide, reusing the real vxc.py/vidyax.py front-end. No server round
 * trip needed — works on static GitHub Pages.
 */

(function () {
  let pyodideReadyPromise = null;

  function basePath() {
    return window.location.pathname.includes('/Vidyax/') ? '/Vidyax/' : './';
  }

  async function initPyodide(onStatus) {
    if (pyodideReadyPromise) return pyodideReadyPromise;

    pyodideReadyPromise = (async () => {
      if (onStatus) onStatus('Loading Python runtime...');
      if (typeof loadPyodide !== 'function') {
        const s = document.createElement('script');
        s.src = 'https://cdn.jsdelivr.net/pyodide/v0.26.1/full/pyodide.js';
        document.head.appendChild(s);
        await new Promise((res, rej) => { s.onload = res; s.onerror = rej; });
      }
      const pyodide = await loadPyodide();

      if (onStatus) onStatus('Fetching Vidyax compiler sources...');
      const base = basePath() + 'assets/py/';
      const [vidyaxSrc, vxcSrc] = await Promise.all([
        fetch(base + 'vidyax.py').then(r => {
          if (!r.ok) throw new Error('vidyax.py not found at ' + base);
          return r.text();
        }),
        fetch(base + 'vxc.py').then(r => {
          if (!r.ok) throw new Error('vxc.py not found at ' + base);
          return r.text();
        }),
      ]);

      pyodide.FS.mkdirTree('/vx_src');
      pyodide.FS.writeFile('/vx_src/vidyax.py', vidyaxSrc);
      pyodide.FS.writeFile('/vx_src/vxc.py', vxcSrc);

      if (onStatus) onStatus('Initializing compiler...');
      pyodide.runPython(`
import sys
if "/vx_src" not in sys.path:
    sys.path.insert(0, "/vx_src")
import vxc
      `);

      return pyodide;
    })();

    return pyodideReadyPromise;
  }

  /**
   * Compile Vidyax source to .vxc bytecode.
   * @returns {Promise<{ok: true, bytes: Uint8Array} | {ok: false, error: string}>}
   */
  async function compileVidyax(sourceCode, onStatus) {
    const pyodide = await initPyodide(onStatus);
    pyodide.globals.set('__vx_source', sourceCode);

    try {
      const result = pyodide.runPython(`
import vxc
from vidyax import VidyaxError
try:
    __vx_bytes = vxc.compile_source(__vx_source).serialize()
    __vx_error = None
except VidyaxError as e:
    __vx_bytes = None
    __vx_error = e.show() if hasattr(e, "show") else str(e)
except Exception as e:
    __vx_bytes = None
    __vx_error = "internal compiler error: " + str(e)
(__vx_bytes, __vx_error)
      `);

      const [pyBytes, error] = result.toJs();
      result.destroy();

      if (error) {
        return { ok: false, error: String(error) };
      }
      // pyodide bytes -> JS: pyBytes is a Uint8Array-backed PyProxy or
      // already a Uint8Array depending on version; normalize both.
      const bytes = pyBytes instanceof Uint8Array
        ? pyBytes
        : new Uint8Array(pyBytes.toJs ? pyBytes.toJs() : pyBytes);
      if (pyBytes && pyBytes.destroy) pyBytes.destroy();

      return { ok: true, bytes };
    } catch (err) {
      return { ok: false, error: String(err && err.message ? err.message : err) };
    }
  }

  window.VidyaxCompiler = { compileVidyax, initPyodide };
})();