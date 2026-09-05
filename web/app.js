(function () {
  'use strict';

  const LOG_MAX_ENTRIES = 200;
  const SLIDER_SEND_DEBOUNCE_MS = 250;

  let INIT = null;
  const cardEls = {};
  let killSwitchTripped = false;

  window.addEventListener('pywebviewready', () => {
    pywebview.api.get_init_data().then(boot);
  });

  function boot(data) {
    INIT = data;
    killSwitchTripped = !!data.killSwitchTripped;
    buildChannelGrid();
    wireTitlebar();
    wireControls();
    wireSensorPanel();
    applySensorState(data.sensor || {});
    setKillSwitchUi(killSwitchTripped);
  }

  // ---------- channel cards ----------

  function buildChannelGrid() {
    const grid = document.getElementById('channels-grid');
    for (const ch of INIT.channels) {
      grid.appendChild(buildChannelCard(ch));
    }
  }

  function buildChannelCard(ch) {
    const el = document.createElement('div');
    el.className = 'card channel-card';
    el.dataset.address = ch.address;

    const modeOptions = INIT.modes
      .map((m) => `<option value="${m.code}">${escapeHtml(m.name)}</option>`)
      .join('');
    const levelLabels = INIT.levelLabels
      .map((label, i) => `<span data-level="${i}">${escapeHtml(label)}</span>`)
      .join('');

    el.innerHTML = `
      <div class="card-header">
        <img src="icons/broadcast-tower.png" alt="">
        <span class="card-title">CH${String(ch.displayNumber).padStart(2, '0')}</span>
      </div>
      <div class="card-body">
        <div class="main-row">
          <div class="left-col">
            <div class="mode-row">
              <select class="mode-select">${modeOptions}</select>
              <button class="mode-set-btn">Set</button>
            </div>
            <div class="power-row">
              <button class="power-btn on-btn">ON</button>
              <button class="power-btn off-btn">OFF</button>
            </div>
            <div class="status-line">
              <span class="status-dot"></span>
              <span class="status-text">STANDBY</span>
            </div>
          </div>
          <div class="slider-row">
            <div class="level-slider-wrap">
              <input type="range" class="level-slider" min="0" max="3" step="1" value="0">
            </div>
            <div class="level-labels">${levelLabels}</div>
          </div>
        </div>
      </div>
    `;

    const refs = {
      root: el,
      modeSelect: el.querySelector('.mode-select'),
      modeSet: el.querySelector('.mode-set-btn'),
      onBtn: el.querySelector('.on-btn'),
      offBtn: el.querySelector('.off-btn'),
      statusDot: el.querySelector('.status-dot'),
      statusText: el.querySelector('.status-text'),
      slider: el.querySelector('.level-slider'),
      levelLabelEls: Array.from(el.querySelectorAll('.level-labels span')),
      sendDebounce: null,
    };
    cardEls[ch.address] = refs;

    refs.onBtn.addEventListener('click', () => {
      // Kill switch blocks powering on, same as the level slider below -
      // OFF is never blocked. Checked here (before the optimistic
      // update) rather than only on the Python side, so a tripped
      // channel's card doesn't flash into a bogus "ON" state that then
      // never gets confirmed.
      if (killSwitchTripped) return;
      // Optimistic local update - the original widget-based UI updated on
      // click, not after a hardware round trip; the real command still
      // has up to a 300ms blind timeout on the Python side before
      // onChannelChanged confirms it (see hooks/use_channel.py).
      applyOptimistic(refs, { outputOn: true, level: ch.lastLevel || 1 });
      pywebview.api.turn_on(ch.address);
    });
    refs.offBtn.addEventListener('click', () => {
      applyOptimistic(refs, { outputOn: false, level: 0 });
      pywebview.api.turn_off(ch.address);
    });
    refs.modeSet.addEventListener('click', () => {
      pywebview.api.set_mode(ch.address, parseInt(refs.modeSelect.value, 10));
    });
    refs.slider.addEventListener('input', () => {
      const level = parseInt(refs.slider.value, 10);
      if (level > 0 && killSwitchTripped) {
        // Snap the slider back rather than letting it sit on a value
        // that was silently refused - Python won't send a state update
        // to correct it (there's nothing to send: the command never
        // went out), so this has to happen client-side. dataset.value is
        // the last value actually applied (see updateSliderVisual), not
        // the stale `ch` this card closed over at construction time.
        const lastApplied = parseInt(refs.slider.dataset.value, 10) || 0;
        refs.slider.value = lastApplied;
        return;
      }
      applyOptimistic(refs, { outputOn: level > 0, level });
      if (refs.sendDebounce) clearTimeout(refs.sendDebounce);
      refs.sendDebounce = setTimeout(() => {
        pywebview.api.set_level(ch.address, level);
      }, SLIDER_SEND_DEBOUNCE_MS);
    });

    applyChannelState(refs, ch);
    return el;
  }

  function applyOptimistic(refs, { outputOn, level }) {
    refs.root.classList.toggle('is-on', outputOn);
    refs.onBtn.classList.toggle('active', outputOn);
    refs.offBtn.classList.toggle('active', !outputOn);
    refs.slider.disabled = !outputOn;
    refs.slider.value = level;
    updateSliderVisual(refs, level);
    updateStatus(refs, level, false);
  }

  function applyChannelState(refs, ch) {
    refs.root.classList.toggle('is-on', ch.outputOn);
    refs.onBtn.classList.toggle('active', ch.outputOn);
    refs.offBtn.classList.toggle('active', !ch.outputOn);
    refs.slider.disabled = !ch.outputOn;
    if (ch.mode !== null && ch.mode !== undefined) {
      refs.modeSelect.value = String(ch.mode);
    }
    refs.slider.value = ch.level;
    updateSliderVisual(refs, ch.level);
    updateStatus(refs, ch.level, false);
  }

  function updateSliderVisual(refs, level) {
    refs.slider.dataset.value = level;
    refs.levelLabelEls.forEach((span) => {
      span.classList.toggle('active', parseInt(span.dataset.level, 10) === level);
    });
  }

  function updateStatus(refs, level, busy) {
    if (busy) {
      refs.statusText.textContent = 'SENDING...';
      refs.statusText.className = 'status-text busy';
      refs.statusDot.classList.remove('on');
      return;
    }
    const isOn = level > 0;
    refs.statusText.textContent = isOn ? INIT.levelLabelsFull[level].toUpperCase() : 'STANDBY';
    refs.statusText.className = 'status-text' + (isOn ? ' on' : '');
    refs.statusDot.classList.toggle('on', isOn);
  }

  // ---------- Python -> JS push ----------

  window.onChannelChanged = function (ch) {
    const refs = cardEls[ch.address];
    if (refs) applyChannelState(refs, ch);
  };

  window.onBusyChanged = function (address, busy) {
    const refs = cardEls[address];
    if (refs && busy) updateStatus(refs, 0, true);
    // The false edge is always followed by a state update from the same
    // command (success, rejection, or blind timeout all call
    // state.update()), which repaints the real status - nothing to do here.
  };

  window.onCommandTimeout = function (message) {
    setStatus(message);
  };

  window.onRawTx = function (address, text) {
    appendLog(`TX CH${String(address).padStart(2, '0')}: ${text}`);
  };

  window.onRawRx = function (address, text) {
    appendLog(`RX CH${String(address).padStart(2, '0')}: ${text}`);
  };

  // ---------- amplifier temperature sensor ----------

  const GAUGE_MAX_C = 80;
  // Confirmed thresholds: 0-19 white/freezing, 20-39 green/low, 40-55
  // blue, 56-65 orange, 66+ red. Drives the numeric reading's text
  // color - the gauge bar itself uses a few smoother interpolation
  // stops (see style.css) for a nicer visual blend between the same
  // colors.
  function tempBandColor(tempC) {
    if (tempC < 20) return '#6B7280'; // "white/freezing" band read against a light card - muted gray reads better than literal white
    if (tempC < 40) return '#16A34A';
    if (tempC < 56) return '#2563EB';
    if (tempC < 66) return '#D97706';
    return '#DC2626';
  }

  function applySensorState(state) {
    const connectBtn = document.getElementById('sensor-connect-btn');
    const tempLabel = document.getElementById('sensor-temp-label');
    const humidityLabel = document.getElementById('sensor-humidity-label');
    const marker = document.getElementById('sensor-gauge-marker');

    connectBtn.textContent = state.connected ? 'Disconnect' : 'Connect';

    if (state.has_reading) {
      const pct = Math.max(0, Math.min(100, (state.temperature_c / GAUGE_MAX_C) * 100));
      marker.style.left = pct + '%';
      marker.hidden = false;
      tempLabel.textContent = `${state.temperature_c.toFixed(1)} C`;
      tempLabel.style.color = tempBandColor(state.temperature_c);
      humidityLabel.textContent = `Humidity: ${state.humidity_pct.toFixed(1)} %`;
    } else {
      marker.hidden = true;
      tempLabel.textContent = '-';
      tempLabel.style.color = '';
      if (!state.connected) {
        humidityLabel.textContent = 'Humidity: -';
      } else {
        humidityLabel.textContent = `Reading... (try ${state.attempt_count || 0}, last ${state.last_rx_len || 0} B)`;
      }
    }
  }

  function setKillSwitchUi(tripped) {
    document.getElementById('kill-switch-row').hidden = !tripped;
  }

  window.onSensorChanged = function (state) {
    applySensorState(state);
  };

  window.onKillSwitchChanged = function (tripped) {
    killSwitchTripped = tripped;
    setKillSwitchUi(tripped);
    if (tripped) {
      appendLog('! KILL SWITCH TRIPPED - amplifier over temperature, all channels forced OFF');
    } else {
      appendLog('Kill switch reset.');
    }
  };

  function wireSensorPanel() {
    const portSelect = document.getElementById('sensor-port-select');
    const connectBtn = document.getElementById('sensor-connect-btn');
    const refreshBtn = document.getElementById('sensor-refresh-btn');
    const resetBtn = document.getElementById('kill-switch-reset-btn');

    function refreshPorts() {
      pywebview.api.sensor_list_ports().then((ports) => {
        const previous = portSelect.value;
        portSelect.innerHTML = '';
        for (const port of ports) {
          const opt = document.createElement('option');
          opt.value = port;
          opt.textContent = port;
          portSelect.appendChild(opt);
        }
        // Keep whatever was selected (loaded from config, or picked by
        // hand) across a refresh instead of always jumping to the first
        // port - a plugged-in device shouldn't silently switch ports
        // just because the list got rebuilt.
        const toSelect = ports.includes(previous) ? previous : (ports.includes(INIT.sensorSavedPort) ? INIT.sensorSavedPort : ports[0]);
        if (toSelect) portSelect.value = toSelect;
      });
    }

    refreshBtn.addEventListener('click', refreshPorts);
    refreshPorts();

    connectBtn.addEventListener('click', () => {
      if (connectBtn.textContent === 'Disconnect') {
        pywebview.api.sensor_disconnect();
        return;
      }
      const port = portSelect.value;
      if (!port) return;
      pywebview.api.sensor_connect(port);
    });

    resetBtn.addEventListener('click', () => {
      pywebview.api.kill_switch_reset();
    });
  }

  // ---------- logs ----------

  function appendLog(line) {
    const list = document.getElementById('logs-list');
    const row = document.createElement('div');
    row.textContent = line;
    list.appendChild(row);
    while (list.children.length > LOG_MAX_ENTRIES) {
      list.removeChild(list.firstChild);
    }
    list.scrollTop = list.scrollHeight;
  }

  // ---------- controls bar ----------

  function setStatus(text) {
    document.getElementById('status-label').textContent = text;
  }

  function wireControls() {
    document.getElementById('btn-clear-log').addEventListener('click', () => {
      pywebview.api.clear_log();
      document.getElementById('logs-list').innerHTML = '';
      setStatus('Log cleared.');
    });

    document.getElementById('btn-query').addEventListener('click', async () => {
      const result = await showQueryDialog();
      if (!result) return;
      setStatus(`Querying ${result.on ? 'ON' : 'OFF'} to address ${result.address}…`);
      pywebview.api.query(result.address, result.on);
    });
  }

  function showQueryDialog() {
    return new Promise((resolve) => {
      const overlay = document.getElementById('confirm-overlay');
      const panel = document.getElementById('confirm-panel');
      const prevHTML = panel.innerHTML;
      panel.innerHTML = `
        <p id="confirm-title">Query</p>
        <p id="confirm-message">Address to send to (0-199):</p>
        <input type="number" id="query-address" min="0" max="199" value="1"
          style="width:100%;margin-bottom:10px;padding:6px;border:1px solid var(--border-subtle);border-radius:4px;font-size:13px;">
        <div style="display:flex;gap:14px;margin-bottom:16px;font-size:13px;color:var(--text-dark);">
          <label><input type="radio" name="query-onoff" value="on" checked> ON</label>
          <label><input type="radio" name="query-onoff" value="off"> OFF</label>
        </div>
        <div id="confirm-buttons">
          <button class="confirm-cancel-btn" id="query-cancel">Cancel</button>
          <button class="confirm-ok-btn" id="query-ok">Query</button>
        </div>
      `;
      overlay.classList.add('visible');
      panel.querySelector('#query-address').focus();

      function cleanup(result) {
        overlay.classList.remove('visible');
        panel.innerHTML = prevHTML;
        resolve(result);
      }

      panel.querySelector('#query-cancel').addEventListener('click', () => cleanup(null));
      panel.querySelector('#query-ok').addEventListener('click', () => {
        const address = parseInt(panel.querySelector('#query-address').value, 10);
        if (Number.isNaN(address) || address < 0 || address > 199) return;
        const on = panel.querySelector('input[name="query-onoff"]:checked').value === 'on';
        cleanup({ address, on });
      });
    });
  }

  function confirmDialog(title, message, confirmText, cancelText, danger) {
    return new Promise((resolve) => {
      const overlay = document.getElementById('confirm-overlay');
      document.getElementById('confirm-title').textContent = title;
      document.getElementById('confirm-message').textContent = message;
      const okBtn = document.getElementById('confirm-ok');
      const cancelBtn = document.getElementById('confirm-cancel');
      okBtn.textContent = confirmText;
      cancelBtn.textContent = cancelText;
      okBtn.className = 'confirm-ok-btn' + (danger ? ' danger' : '');
      overlay.classList.add('visible');

      function cleanup(result) {
        overlay.classList.remove('visible');
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        resolve(result);
      }
      function onOk() {
        cleanup(true);
      }
      function onCancel() {
        cleanup(false);
      }
      okBtn.addEventListener('click', onOk);
      cancelBtn.addEventListener('click', onCancel);
    });
  }

  // ---------- titlebar ----------

  function wireTitlebar() {
    document.getElementById('btn-minimize').addEventListener('click', () => pywebview.api.minimize());
    document.getElementById('btn-maximize').addEventListener('click', () => pywebview.api.toggle_maximize());
    document.getElementById('titlebar').addEventListener('dblclick', (e) => {
      if (e.target.closest('.caption-btn')) return;
      pywebview.api.toggle_maximize();
    });
    document.getElementById('btn-close').addEventListener('click', async () => {
      const confirmed = await confirmDialog(
        'Close App',
        'Close the app? Channel power states are left as they are - this does not turn anything off.',
        'Close',
        'Cancel',
        true
      );
      if (confirmed) pywebview.api.close_app();
    });

    const titlebar = document.getElementById('titlebar');
    let drag = null;
    let pendingFrame = false;

    titlebar.addEventListener('mousedown', (e) => {
      if (e.target.closest('.caption-btn') || e.button !== 0) return;
      pywebview.api.get_window_position().then((pos) => {
        drag = { mouseX: e.screenX, mouseY: e.screenY, winX: pos[0], winY: pos[1] };
      });
    });
    document.addEventListener('mousemove', (e) => {
      if (!drag || pendingFrame) return;
      pendingFrame = true;
      requestAnimationFrame(() => {
        pendingFrame = false;
        if (!drag) return;
        pywebview.api.move_window(
          drag.winX + (e.screenX - drag.mouseX),
          drag.winY + (e.screenY - drag.mouseY)
        );
      });
    });
    document.addEventListener('mouseup', () => {
      drag = null;
    });
  }

  // ---------- utils ----------

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }
})();
