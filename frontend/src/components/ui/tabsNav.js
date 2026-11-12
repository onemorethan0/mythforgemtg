// Arrow-key logic for Tabs, kept pure so it can be tested without a DOM.
// Left/Right move to the neighbouring tab and wrap; Home/End jump to the ends; any other key leaves
// the selection alone. An unknown current tab falls back to the first one.
export function nextTab(keys, current, key) {
  if (!keys.length) return current
  const i = keys.indexOf(current)
  if (i < 0) return keys[0]
  if (key === 'ArrowRight') return keys[(i + 1) % keys.length]
  if (key === 'ArrowLeft') return keys[(i - 1 + keys.length) % keys.length]
  if (key === 'Home') return keys[0]
  if (key === 'End') return keys[keys.length - 1]
  return current
}
