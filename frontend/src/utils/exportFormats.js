// The list formats the server can write (deck_export.py), labelled for the UI. The server defines
// what each one contains; this only names them. Shared by the deck page's Export menu and the
// History page's batch export.
export const EXPORT_FORMATS = [
  { key: 'moxfield', label: 'Moxfield / Archidekt', hint: 'names with set codes' },
  { key: 'arena',    label: 'MTG Arena',            hint: 'Commander + Deck sections' },
  { key: 'mtgo',     label: 'MTG Online',           hint: 'plain names, command zone as SB' },
  { key: 'text',     label: 'Plain text',           hint: 'names only; re-imports here' },
  { key: 'csv',      label: 'Spreadsheet (CSV)',    hint: 'one row per card' },
  { key: 'backup',   label: 'Backup (JSON)',        hint: 'the saved deck data' },
]
