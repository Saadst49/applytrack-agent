const $ = id => document.getElementById(id);
let session = crypto.randomUUID();
let count = 0;

function message(role, text) {
	const article = document.createElement('article');
	article.className = `message ${role}`;
	const label = document.createElement('span');
	label.className = 'message-label';
	label.textContent = role === 'user' ? 'You' : 'ApplyTrack Agent';
	const content = document.createElement('p');
	content.textContent = text;
	article.append(label, content);
	$('messages').append(article);
	article.scrollIntoView({ block: 'nearest' });
}

function setStatus(status, tone = 'idle') {
	const element = $('status');
	element.textContent = status;
	element.className = `status-pill ${tone}`;
}

function renderRun(data) {
	setStatus(data.status, data.status === 'completed' ? 'success' : data.status === 'failed' || data.status === 'tool_error' ? 'error' : 'active');
	$('stop-reason').textContent = data.stop_reason || '-';
	$('steps').textContent = data.steps ?? 0;
	$('trace').textContent = data.tool_calls?.length ? JSON.stringify(data.tool_calls, null, 2) : 'No tool calls.';
	$('observations').textContent = data.events?.length ? JSON.stringify(data.events, null, 2) : 'No events.';
}

async function init() {
	try {
		const [modelResponse, healthResponse] = await Promise.all([fetch('/models'), fetch('/health')]);
		if (!modelResponse.ok) throw new Error('Models unavailable');
		const modelData = await modelResponse.json();
		modelData.models.forEach(model => {
			const option = document.createElement('option');
			option.value = model;
			option.textContent = model;
			$('model').append(option);
		});
		if (healthResponse.ok) {
			const health = await healthResponse.json();
			$('health').textContent = health.implementation || 'Service online';
			$('health').classList.add('online');
		}
	} catch (error) {
		setStatus('Unavailable', 'error');
		$('health').textContent = 'Service unavailable';
		$('send').disabled = true;
	}
}

$('chat').onsubmit = async event => {
	event.preventDefault();
	const task = $('task').value.trim();
	if (!task) return;
	const note = $('external').value.trim();
	message('user', task);
	$('send').disabled = true;
	$('reset').disabled = true;
	setStatus('Running', 'active');
	$('stop-reason').textContent = 'Waiting for result';
	$('trace').textContent = 'Waiting for result...';
	$('observations').textContent = 'Waiting for result...';
	try {
		const response = await fetch('/chat', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				session_id: session,
				task,
				model: $('model').value,
				external_context: note ? [{ source: 'browser-note', content: note, trust: 'untrusted' }] : [],
			}),
		});
		const data = await response.json();
		if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The request could not be completed.');
		message('agent', data.final_response);
		count += 2;
		$('memory').textContent = `${count} messages exchanged; server retains at most 12`;
		renderRun(data);
		$('task').value = '';
	} catch (error) {
		setStatus('Request failed', 'error');
		$('stop-reason').textContent = 'request_error';
	} finally {
		$('send').disabled = false;
		$('reset').disabled = false;
	}
};

document.querySelectorAll('[data-example]').forEach(button => {
	button.onclick = () => { $('task').value = button.dataset.example; $('task').focus(); };
});

$('reset').onclick = async () => {
	try {
		const response = await fetch(`/chat/${session}`, { method: 'DELETE' });
		if (!response.ok) throw new Error('Reset failed');
		session = crypto.randomUUID();
		count = 0;
		$('messages').innerHTML = '<div class="empty-state"><strong>What should we track?</strong><span>Search, update, or draft from your sandbox records.</span></div>';
		$('memory').textContent = '0 messages in this chat';
		$('external').value = '';
		$('task').value = '';
		setStatus('Idle', 'idle');
		$('stop-reason').textContent = '-';
		$('steps').textContent = '0';
		$('trace').textContent = 'No tool calls yet.';
		$('observations').textContent = 'No observations yet.';
	} catch (error) {
		setStatus('Reset failed', 'error');
	}
};

init();
