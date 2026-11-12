// What a tap on a dock tab does when the dock is a bottom sheet (narrow windows).
// Tapping a tab opens the sheet on it; tapping the tab that is already open folds the sheet away;
// tapping another tab while open just switches. Pure, so it can be tested without a DOM.
export function sheetTabAction(currentTab, clickedTab, isOpen) {
  if (isOpen && clickedTab === currentTab) return { tab: clickedTab, open: false }
  return { tab: clickedTab, open: true }
}
