const $ = id => document.getElementById(id);
let history = [], imageData = null, recorder = null, audioChunks = [], cameraStream = null, lastAnswer = '';

const headers = () => {
  const h = {};
  const token = $('token').value.trim();
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
};

function formatModelName(modelId) {
  if (!modelId) return '';
  if (modelId.includes('gemini-2.5-flash') || modelId.includes('gemini-3.8-flash')) return 'Gemini 3.8 Flash';
  if (modelId.includes('gemini-2.0-flash')) return 'Gemini 2.0 Flash';
  if (modelId.includes('claude-3-5-sonnet')) return 'Claude 3.5 Sonnet';
  if (modelId.includes('claude-3-5-haiku')) return 'Claude 3.5 Haiku';
  if (modelId.includes('gpt-4.1-mini')) return 'GPT-4.1 Mini';
  if (modelId.includes('gpt-4o-mini')) return 'GPT-4o Mini';
  return modelId;
}

function bubble(text, kind = 'bot', sources = [], modelUsed = '') {
  const el = document.createElement('article');
  el.className = kind;
  el.textContent = text;

  if (sources.length || modelUsed) {
    const meta = document.createElement('div');
    meta.className = 'meta-footer';

    if (modelUsed) {
      const badge = document.createElement('span');
      badge.className = 'model-badge';
      badge.textContent = formatModelName(modelUsed);
      meta.appendChild(badge);
    }

    if (sources.length) {
      const s = document.createElement('span');
      s.className = 'sources';
      s.textContent = '• Sources: ' + sources.slice(0, 8).map(x => x.type === 'pdf' ? `PDF p.${x.page}` : (x.title || x.url)).join(' | ');
      meta.appendChild(s);
    }

    el.appendChild(meta);
  }

  $('messages').appendChild(el);
  $('messages').scrollTop = $('messages').scrollHeight;
  return el;
}

async function checkHealth() {
  try {
    const r = await fetch('/api/health');
    const d = await r.json();

    const prov = d.providers || {};
    const configuredAny = prov.openai || prov.gemini || prov.anthropic;

    $('status').textContent = configuredAny ? '● Connected' : '⚠ API keys needed';
    if (!prov.pinecone) {
      $('status').textContent += ' (Pinecone offline)';
    }

    // Populate provider badges in settings details
    const container = $('providerStatus');
    if (container) {
      container.innerHTML = `
        <span class="provider-pill ${prov.gemini ? 'active' : ''}">Google Gemini: ${prov.gemini ? 'Active' : 'Not set'}</span>
        <span class="provider-pill ${prov.anthropic ? 'active' : ''}">Anthropic Claude: ${prov.anthropic ? 'Active' : 'Not set'}</span>
        <span class="provider-pill ${prov.openai ? 'active' : ''}">OpenAI: ${prov.openai ? 'Active' : 'Not set'}</span>
        <span class="provider-pill ${prov.pinecone ? 'active' : ''}">Pinecone KB: ${prov.pinecone ? 'Active' : 'Not set'}</span>
        <span class="provider-pill ${prov.tavily ? 'active' : ''}">Tavily Search: ${prov.tavily ? 'Active' : 'Not set'}</span>
      `;
    }

    if (d.default_model && $('modelSelect')) {
      for (const opt of $('modelSelect').options) {
        if (opt.value === d.default_model) {
          opt.selected = true;
          break;
        }
      }
    }
  } catch {
    $('status').textContent = '● Server offline';
  }
}
checkHealth();

function setImage(file) {
  if (!file) return;
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 5e6) {
    alert('Use PNG/JPEG/WebP under 5MB');
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    imageData = reader.result;
    $('thumbnail').src = imageData;
    $('preview').hidden = false;
  };
  reader.readAsDataURL(file);
}

$('image').addEventListener('change', e => setImage(e.target.files[0]));
$('remove').onclick = () => {
  imageData = null;
  $('preview').hidden = true;
  $('image').value = '';
};

$('chatForm').addEventListener('submit', async e => {
  e.preventDefault();
  const message = $('message').value.trim();
  if (!message) return;

  const prior = history.slice(-8);
  const selectedModel = $('modelSelect')?.value || 'gpt-4.1-mini';

  bubble(message, 'user');
  $('message').value = '';
  $('send').disabled = true;
  const pending = bubble('Thinking with ' + formatModelName(selectedModel) + '…');

  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: { ...headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        history: prior,
        image_data: imageData,
        model: selectedModel
      })
    });

    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Request failed');

    pending.textContent = d.answer;
    lastAnswer = d.answer;

    if (d.sources?.length || d.model_used) {
      const meta = document.createElement('div');
      meta.className = 'meta-footer';

      if (d.model_used) {
        const badge = document.createElement('span');
        badge.className = 'model-badge';
        badge.textContent = formatModelName(d.model_used);
        meta.appendChild(badge);
      }

      if (d.sources?.length) {
        const src = document.createElement('span');
        src.className = 'sources';
        src.textContent = '• Sources: ' + d.sources.slice(0, 8).map(x => x.type === 'pdf' ? `PDF p.${x.page}` : (x.title || x.url)).join(' | ');
        meta.appendChild(src);
      }

      pending.appendChild(meta);
    }

    history.push({ role: 'user', content: message }, { role: 'assistant', content: d.answer });
    $('remove').click();
  } catch (err) {
    pending.textContent = '⚠️ ' + err.message;
  } finally {
    $('send').disabled = false;
    $('messages').scrollTop = $('messages').scrollHeight;
  }
});

$('mic').onclick = async () => {
  if (recorder && recorder.state === 'recording') {
    recorder.stop();
    $('mic').textContent = '🎤 Voice';
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = e => audioChunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(audioChunks, { type: recorder.mimeType });
      const data = new FormData();
      data.append('file', blob, 'voice.webm');
      $('mic').disabled = true;
      try {
        const r = await fetch('/api/transcribe', { method: 'POST', headers: headers(), body: data });
        const out = await r.json();
        if (!r.ok) throw Error(out.detail);
        $('message').value = out.text;
      } catch (e) {
        alert(e.message);
      } finally {
        $('mic').disabled = false;
      }
    };
    recorder.start();
    $('mic').textContent = '⏹ Stop recording';
  } catch (e) {
    alert('Microphone unavailable: ' + e.message);
  }
};

$('listen').onclick = async () => {
  if (!lastAnswer) return alert('Ask a question first');
  $('listen').disabled = true;
  try {
    const r = await fetch('/api/speak', {
      method: 'POST',
      headers: { ...headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: lastAnswer })
    });
    if (!r.ok) throw Error('Speech unavailable');
    const url = URL.createObjectURL(await r.blob());
    const audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    await audio.play();
  } catch (e) {
    alert(e.message);
  } finally {
    $('listen').disabled = false;
  }
};

$('camera').onclick = async () => {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
    $('video').srcObject = cameraStream;
    $('video').hidden = false;
    $('cameraActions').hidden = false;
  } catch (e) {
    alert('Camera unavailable: ' + e.message);
  }
};

$('closeCamera').onclick = () => {
  cameraStream?.getTracks().forEach(t => t.stop());
  cameraStream = null;
  $('video').hidden = true;
  $('cameraActions').hidden = true;
};

$('snap').onclick = () => {
  const v = $('video'), c = $('canvas');
  c.width = v.videoWidth;
  c.height = v.videoHeight;
  c.getContext('2d').drawImage(v, 0, 0);
  c.toBlob(b => setImage(new File([b], 'camera.jpg', { type: 'image/jpeg' })), 'image/jpeg', .85);
  $('closeCamera').click();
};
