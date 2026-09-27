(() => {
  const maxLengthInput = document.getElementById('maxLength');
  const editor = document.getElementById('editor');
  const backdrop = document.getElementById('backdrop');
  const countText = document.getElementById('countText');
  const overflowText = document.getElementById('overflowText');
  const copyBtn = document.getElementById('copyBtn');
  const saveBtn = document.getElementById('saveBtn');

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function render() {
    const max = Math.max(1, parseInt(maxLengthInput.value, 10) || 0);
    const text = editor.value;
    // 문자 수(코드 유닛) 기준. 완성형 한글 음절은 1글자 = 1코드 유닛이라
    // 별도 처리 없이도 정확히 세어지고, 공백/줄바꿈도 그대로 포함됩니다.
    const length = text.length;

    let html;
    if (length > max) {
      const normalPart = text.slice(0, max);
      const overflowPart = text.slice(max);
      html =
        escapeHtml(normalPart) +
        '<span class="overflow-mark">' + escapeHtml(overflowPart) + '</span>';
    } else {
      html = escapeHtml(text);
    }

    // 마지막 줄이 개행으로 끝나면 스크롤 높이가 어긋날 수 있어 보정
    if (text.endsWith('\n')) {
      html += ' ';
    }

    backdrop.innerHTML = html;

    const over = length > max;
    countText.textContent =
      length.toLocaleString() + ' / ' + max.toLocaleString() + ' (공백 포함)';
    countText.classList.toggle('over-limit', over);

    if (over) {
      overflowText.textContent = (length - max).toLocaleString() + '자 초과';
      overflowText.hidden = false;
    } else {
      overflowText.hidden = true;
    }

    syncScroll();
  }

  function syncScroll() {
    backdrop.scrollTop = editor.scrollTop;
    backdrop.scrollLeft = editor.scrollLeft;
  }

  function buildFileName() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return (
      '글쓰기_' +
      now.getFullYear() + pad(now.getMonth() + 1) + pad(now.getDate()) + '_' +
      pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds()) +
      '.md'
    );
  }

  function showFeedback(button, tempLabel, originalLabel) {
    button.textContent = tempLabel;
    button.disabled = true;
    setTimeout(() => {
      button.textContent = originalLabel;
      button.disabled = false;
    }, 1200);
  }

  function saveAsMarkdown() {
    const blob = new Blob([editor.value], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = buildFileName();
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showFeedback(saveBtn, '저장됨', '저장 (.md)');
  }

  function fallbackCopy(text, done) {
    const temp = document.createElement('textarea');
    temp.value = text;
    temp.style.position = 'fixed';
    temp.style.opacity = '0';
    document.body.appendChild(temp);
    temp.select();
    try {
      document.execCommand('copy');
      done();
    } catch (err) {
      // 클립보드 접근이 막힌 환경에서는 조용히 무시합니다.
    }
    document.body.removeChild(temp);
  }

  function copyToClipboard() {
    const text = editor.value;
    const done = () => showFeedback(copyBtn, '복사됨', '복사');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
    } else {
      fallbackCopy(text, done);
    }
  }

  editor.addEventListener('input', render);
  editor.addEventListener('scroll', syncScroll);
  maxLengthInput.addEventListener('input', render);
  window.addEventListener('resize', syncScroll);
  copyBtn.addEventListener('click', copyToClipboard);
  saveBtn.addEventListener('click', saveAsMarkdown);

  render();
})();
