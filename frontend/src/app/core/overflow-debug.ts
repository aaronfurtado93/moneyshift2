/**
 * Open any page with ?debug=1 to see which elements are wider than the screen.
 * Wide elements are what make a phone browser shrink the whole page.
 */
export function showOverflowReport(): void {
  if (!/[?&]debug=1\b/.test(location.search)) return;
  const render = () => {
    const w = document.documentElement.clientWidth;
    const rows = [...document.body.querySelectorAll<HTMLElement>('*')]
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.width > 0 && r.right > w + 1)
      .sort((a, b) => b.r.right - a.r.right)
      .slice(0, 8)
      .map(({ el, r }) => `${el.tagName.toLowerCase()}.${String(el.className).split(' ')[0]} right=${Math.round(r.right)} w=${Math.round(r.width)}`);
    let box = document.getElementById('ms-debug');
    if (!box) {
      box = document.createElement('pre');
      box.id = 'ms-debug';
      box.style.cssText = 'position:fixed;left:0;bottom:0;right:0;z-index:99999;margin:0;padding:8px;font:12px/1.3 monospace;background:#000c;color:#0f0;white-space:pre-wrap';
      document.body.appendChild(box);
    }
    box.textContent = `viewport ${w}px, scrollWidth ${document.documentElement.scrollWidth}px\n` + (rows.join('\n') || 'nothing is wider than the screen');
  };
  setTimeout(render, 1500);
  setTimeout(render, 4000);
}
