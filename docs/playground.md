# Vidyax Interactive Playground

Tulis dan jalankan kode Vidyax langsung di browser!

<textarea id="code" style="width: 100%; height: 200px; background: #1e1e1e; color: #6a9fb5; font-family: monospace; padding: 12px; border-radius: 6px; border: 1px solid #333;" placeholder="Tulis kode .vx di sini..."></textarea>

<button onclick="runVidyax()" style="padding: 10px 24px; background: #007acc; color: white; border: none; border-radius: 4px; cursor: pointer; margin-top: 10px; font-weight: bold;">▶ Run Code</button>

### Output Console:
<pre id="output" style="background: #000; color: #00ff00; padding: 15px; border-radius: 6px; min-height: 120px; font-family: monospace;"></pre>

<!-- Load Glue Code Emscripten -->
<script>
  var Module = {
    print: function(text) {
      var out = document.getElementById('output');
      out.innerText += text + "\n";
    }
  };
</script>
<script src="../vidyax_vm.js"></script>

<script>
  function runVidyax() {
    document.getElementById('output').innerText = "";
    var sourceCode = document.getElementById('code').value;
    
    if (window.Module && Module.ccall) {
      Module.ccall('run_from_js', null, ['string'], [sourceCode]);
    } else {
      document.getElementById('output').innerText = "VM sedang dimuat, tunggu sebentar...";
    }
  }
</script>
