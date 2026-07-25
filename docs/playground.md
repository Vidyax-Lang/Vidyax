# Vidyax Playground

Tulis dan uji coba kode Vidyax secara langsung di browser.

<div style="margin-top: 20px;">
  <textarea id="code" spellcheck="false" autocorrect="off" autocapitalize="off" style="width: 100%; height: 220px; background: #1e1e1e; color: #a6e22e; font-family: monospace; padding: 12px; border-radius: 6px; border: 1px solid #333; resize: vertical;" placeholder="// Type your .vx code here...">print "tes"</textarea>
</div>

<button onclick="runVidyax()" style="margin-top: 12px; padding: 10px 20px; background-color: #20e3b2; color: #121212; border: none; font-weight: bold; border-radius: 4px; cursor: pointer;">
  ► Run Code
</button>

<h3 style="margin-top: 24px;">Output Console:</h3>
<pre id="output" style="background: #121212; color: #00ff66; padding: 16px; border-radius: 6px; min-height: 80px; font-family: monospace; border: 1px solid #222; white-space: pre-wrap;"></pre>

<script>
  // Inisialisasi Module Emscripten
  if (typeof window.Module === 'undefined') {
    window.Module = {
      print: function(text) {
        var out = document.getElementById('output');
        if (out) out.innerText += text + "\n";
      },
      printErr: function(text) {
        console.error(text);
      }
    };
  }

  // Load vidyax_vm.js secara dinamis agar tidak error redeclaration
  if (!window.vidyaxScriptLoaded) {
    window.vidyaxScriptLoaded = true;
    var script = document.createElement('script');
    script.src = 'vidyax_vm.js';
    document.head.appendChild(script);
  }

  function runVidyax() {
    var out = document.getElementById('output');
    out.innerText = "";
    var sourceCode = document.getElementById('code').value;
    
    if (typeof window.Module !== 'undefined' && typeof window.Module.ccall === 'function') {
      window.Module.ccall('run_from_js', null, ['string'], [sourceCode]);
    } else {
      out.innerText = "Waiting for WASM module to load...";
    }
  }
</script>