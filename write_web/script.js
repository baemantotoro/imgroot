(() => {
  const maxLengthInput = document.getElementById('maxLength');
  const editor = document.getElementById('editor');
  const backdrop = document.getElementById('backdrop');
  const countText = document.getElementById('countText');
  const overflowText = document.getElementById('overflowText');

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function render() {
    const max = Math.max(1, parseInt(maxLengthInput.value, 10) || 0);
    const text = editor.value;
    const length = text.length; // 문자 수(코드 유닛) 기준

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
    countText.textContent = length.toLocaleString() + ' / ' + max.toLocaleString();
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

  editor.addEventListener('input', render);
  editor.addEventListener('scroll', syncScroll);
  maxLengthInput.addEventListener('input', render);
  window.addEventListener('resize', syncScroll);

  render();
})();
