# Vidyax Playground

Test and execute your Vidyax code directly in the browser.

<div style="margin-top: 20px;">
  <textarea id="code" spellcheck="false" autocorrect="off" autocapitalize="off" style="width: 100%; height: 220px; background: #1e1e1e; color: #a6e22e; font-family: monospace; padding: 12px; border-radius: 6px; border: 1px solid #333; resize: vertical;" placeholder="// Type your .vx code here...">print "test"</textarea>
</div>

<button id="run-btn" onclick="runVidyax()" style="margin-top: 12px; padding: 10px 20px; background-color: #20e3b2; color: #121212; border: none; font-weight: bold; border-radius: 4px; cursor: pointer;">
  ► Run Code
</button>

<h3 style="margin-top: 24px;">Output Console:</h3>
<pre id="output" style="background: #121212; color: #00ff66; padding: 16px; border-radius: 6px; min-height: 80px; font-family: monospace; border: 1px solid #222; white-space: pre-wrap;"></pre>

<script>
(function () {
  var basePath = window.location.pathname.includes('/Vidyax/') ? '/Vidyax/' : '/';

  if (!document.getElementById('vidyax-bridge-script')) {
    var bridge = document.createElement('script');
    bridge.id = 'vidyax-bridge-script';
    bridge.src = basePath + 'assets/js/pyodide-bridge.js';
    document.head.appendChild(bridge);
  }

  if (!window.VidyaxModule) {
    var script = document.createElement('script');
    script.src = basePath + 'vidyax.js';   // built with -s EXPORT_NAME="VidyaxModule"
    document.head.appendChild(script);
  }

  var check = setInterval(function () {
    if (typeof window.VidyaxModule === 'function') {
      clearInterval(check);
      window.VidyaxModule({
        print: function (t) { appendOutput(t + "\n"); },
        printErr: function (t) { console.error(t); }
      }).then(function (instance) {
        window.vxInstance = instance;
      });
    }
  }, 50);

  window.appendOutput = function (text) {
    var out = document.getElementById('output');
    if (out) out.innerText += text;
  };
})();

async function runVidyax() {
  var out = document.getElementById('output');
  var btn = document.getElementById('run-btn');
  if (out) out.innerText = "";
  btn.disabled = true;

  try {
    if (!window.vxInstance || typeof window.vxInstance.ccall !== 'function') {
      appendOutput("[vidyax] WASM module still loading, try again in a moment...\n");
      return;
    }

    var sourceCode = document.getElementById('code').value;

    appendOutput("[vidyax] compiling...\n");
    var result = await window.VidyaxCompiler.compileVidyax(sourceCode, function (status) {
      appendOutput("[vidyax] " + status + "\n");
    });

    if (!result.ok) {
      appendOutput("[compile error]\n" + result.error + "\n");
      return;
    }

    out.innerText = "";  // clear the "compiling..." status before program output
    var exitCode = window.vxInstance.ccall(
      'run_from_js',
      'number',
      ['array', 'number', 'number', 'number'],
      [result.bytes, result.bytes.length, /*allow_net=*/0, /*allow_fs=*/0]
    );

    if (exitCode !== 0) {
      appendOutput("\n[vidyax] exited with code " + exitCode + "\n");
    }
  } finally {
    btn.disabled = false;
  }
}
</script>