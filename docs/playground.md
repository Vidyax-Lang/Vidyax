# Vidyax Playground

Test and execute your Vidyax code directly in your browser.

<div style="margin-top: 20px;">
  <textarea id="code" spellcheck="false" autocorrect="off" autocapitalize="off" style="width: 100%; height: 220px; background: #1e1e1e; color: #a6e22e; font-family: monospace; padding: 12px; border-radius: 6px; border: 1px solid #333; resize: vertical;" placeholder="// Type your .vx code here...">print "tes"</textarea>
</div>

<button onclick="runVidyax()" style="margin-top: 12px; padding: 10px 20px; background-color: #20e3b2; color: #121212; border: none; font-weight: bold; border-radius: 4px; cursor: pointer;">
  ► Run Code
</button>

<h3 style="margin-top: 24px;">Output Console:</h3>
<pre id="output" style="background: #121212; color: #00ff66; padding: 16px; border-radius: 6px; min-height: 80px; font-family: monospace; border: 1px solid #222; white-space: pre-wrap;"></pre>

<script>
(function() {
 
  window.Module = window.Module || {
    print: function(text) {
      var out = document.getElementById('output');
      if (out) out.innerText += text + "\n";
    },
    printErr: function(text) {
      console.error(text);
    }
  };

  // Hanya muat tag script jika belum pernah dimuat sama sekali
  if (!document.getElementById('vidyax-wasm-script')) {
    var script = document.createElement('script');
    script.id = 'vidyax-wasm-script';
    script.src = 'vidyax_vm.js';
    document.head.appendChild(script);
  }
})();

function runVidyax() {
  var out = document.getElementById('output');
  if (out) out.innerText = "";
  var sourceCode = document.getElementById('code').value;
  
  if (typeof window.Module !== 'undefined' && typeof window.Module.ccall === 'function') {
    window.Module.ccall('run_from_js', null, ['string'], [sourceCode]);
  } else {
    if (out) out.innerText = "Waiting for WASM module to load...";
  }
}
</script>