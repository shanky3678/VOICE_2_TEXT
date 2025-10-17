index = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Record → WAV → Transcribe</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 32px; max-width: 800px; }
      h1 { margin: 0 0 16px; }
      .row { margin: 12px 0; }
      button { padding: 10px 16px; border-radius: 8px; border: 1px solid #e5e7eb; cursor: pointer; }
      #log, #out { white-space: pre-wrap; background:#fafafa; padding:12px; border-radius:8px; min-height: 48px; }
      input[type="text"] { padding: 8px 10px; border: 1px solid #e5e7eb; border-radius: 8px; }
    </style>
  </head>
  <body>
    <h1>🎙️ Record to WAV & Transcribe</h1>

    <div class="row">
      <button id="recBtn">Start Recording</button>
      <button id="stopBtn" disabled>Stop</button>
      <span id="timer">00:00</span>
    </div>

    <!-- removed -->

    <div class="row"><strong>Log</strong><div id="log">–</div></div>
    <div class="row"><strong>Transcript</strong><div id="out">–</div></div>
    <div class="row"><strong>Preview</strong><div id="preview">–</div></div>

    <script>
      // ------- Minimal WAV encoder (mono, 16-bit PCM) -------
      function encodeWAV(samples, sampleRate) {
        const numFrames = samples.length;
        const bytesPerSample = 2;
        const blockAlign = bytesPerSample * 1;
        const byteRate = sampleRate * blockAlign;
        const dataSize = numFrames * bytesPerSample;
        const buffer = new ArrayBuffer(44 + dataSize);
        const view = new DataView(buffer);

        writeStr(view, 0, 'RIFF');
        view.setUint32(4, 36 + dataSize, true);
        writeStr(view, 8, 'WAVE');

        writeStr(view, 12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, byteRate, true);
        view.setUint16(32, blockAlign, true);
        view.setUint16(34, 16, true);

        writeStr(view, 36, 'data');
        view.setUint32(40, dataSize, true);

        floatTo16BitPCM(view, 44, samples);
        return new Blob([view], { type: 'audio/wav' });

        function writeStr(dv, offset, str) {
          for (let i = 0; i < str.length; i++) dv.setUint8(offset + i, str.charCodeAt(i));
        }
        function floatTo16BitPCM(dv, offset, input) {
          let pos = 0;
          for (let i = 0; i < input.length; i++, pos += 2) {
            let s = Math.max(-1, Math.min(1, input[i]));
            dv.setInt16(offset + pos, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
          }
        }
      }

      // ------- Recorder using ScriptProcessorNode -------
      let audioCtx, mediaStream, source, processor;
      let recording = false;
      let chunks = [];
      let sampleRate = 48000;
      let wavBlob = null;
      let startTime = 0, timerId = null;

      const recBtn = document.getElementById('recBtn');
      const stopBtn = document.getElementById('stopBtn');
      const logEl = document.getElementById('log');
      const outEl = document.getElementById('out');
      const prevEl = document.getElementById('preview');
      const timerEl = document.getElementById('timer');
      const langEl = document.getElementById('lang'); // may be null (we removed the field)

      function log(msg) { logEl.textContent = msg; }

      recBtn.onclick = async () => {
        try {
          if (recording) return;
          wavBlob = null;
          outEl.textContent = '–';
          prevEl.textContent = '–';

          mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
          audioCtx = new (window.AudioContext || window.webkitAudioContext)();
          sampleRate = audioCtx.sampleRate;
          source = audioCtx.createMediaStreamSource(mediaStream);
          processor = audioCtx.createScriptProcessor(4096, 1, 1);

          chunks = [];
          processor.onaudioprocess = (e) => {
            if (!recording) return;
            const input = e.inputBuffer.getChannelData(0);
            chunks.push(new Float32Array(input));
          };

          source.connect(processor);
          // Some browsers require a connected graph; to avoid audible feedback you can route to a muted GainNode instead:
          // const gain = audioCtx.createGain(); gain.gain.value = 0; processor.connect(gain); gain.connect(audioCtx.destination);
          processor.connect(audioCtx.destination);

          recording = true;
          recBtn.disabled = true;
          stopBtn.disabled = false;
          startTimer();
          log('Recording…');
        } catch (err) {
          log('Mic error: ' + err.message);
        }
      };

      stopBtn.onclick = async () => {
        if (!recording) return;
        recording = false;
        recBtn.disabled = false;
        stopBtn.disabled = true;
        stopTimer();

        try { processor && processor.disconnect(); } catch {}
        try { source && source.disconnect(); } catch {}
        try { audioCtx && audioCtx.close(); } catch {}
        try { mediaStream && mediaStream.getTracks().forEach(t => t.stop()); } catch {}

        const length = chunks.reduce((a, b) => a + b.length, 0);
        const merged = new Float32Array(length);
        let offset = 0;
        for (const c of chunks) { merged.set(c, offset); offset += c.length; }

        wavBlob = encodeWAV(merged, sampleRate);
        log(`Recorded ${(length / sampleRate).toFixed(2)}s @ ${sampleRate} Hz, ${(wavBlob.size/1024).toFixed(1)} KB`);

        await sendToTranscribe();

        const url = URL.createObjectURL(wavBlob);
        prevEl.innerHTML = '';
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.src = url;
        prevEl.appendChild(audio);
      };

      async function sendToTranscribe()  {
        if (!wavBlob) { log('No audio to send'); return; }
        log('Uploading…');
        outEl.textContent = 'Transcribing…';

        const fd = new FormData();
        const filename = `recording_${Date.now()}.wav`;
        fd.append('audio', wavBlob, filename);

        // Guard: langEl might not exist
        const lang = (langEl && langEl.value ? langEl.value : '').trim();
        if (lang) fd.append('language', lang);

        try {
          const res = await fetch('/transcribe', { method: 'POST', body: fd });
          const j = await res.json();
          if (!res.ok) throw new Error(j.detail || 'Failed');
          outEl.textContent = j.text || '(empty transcript)';
          log('Done.');
        } catch (e) {
          outEl.textContent = 'Error: ' + e.message;
          log('Upload/transcribe failed.');
        }
      }

      function startTimer() {
        startTime = Date.now();
        timerId = setInterval(() => {
          const s = Math.floor((Date.now() - startTime) / 1000);
          const mm = String(Math.floor(s / 60)).padStart(2, '0');
          const ss = String(s % 60).padStart(2, '0');
          timerEl.textContent = `${mm}:${ss}`;
        }, 250);
      }
      function stopTimer() { clearInterval(timerId); timerId = null; }
    </script>
  </body>
</html>


"""
