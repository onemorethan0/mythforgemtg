/**
 * Worked examples:
 * | input | call | result |
 * |---|---|---|
 * | `{colors:null, mana_cost:'{2}{W/U}{B}'}` | `cardColors` | `['W','U','B']` |
 * | `{cmc:undefined, mana_cost:'{X}{2/W}{G}'}` | `cardManaValue` | `3` |
 * | `{original_type_line:'Artifact Land', type_line:'Artifact Land'}` | `primaryType` | `'Land'` |
 * | `{quantity:'34'}` | `qty` | `34` |
 * | `[Forest x34 qty]`, by `'color'` | `groupCards` | `[{key:'land', label:'Lands', count:34}]` |
 * | Mind Stone with roles `['draw','ramp']`, by `'role'` | `groupCards` | groups `ramp` then `draw`, each holding Mind Stone |
 */

export const GROUP_BYS = ['type', 'role', 'color', 'cmc', 'none']
export const GROUP_BY_LABELS = { type: 'Card type', role: 'Role', color: 'Color', cmc: 'Mana value', none: 'No grouping' }

export const TYPE_ORDER = ['Creature', 'Instant', 'Sorcery', 'Enchantment', 'Artifact', 'Planeswalker', 'Land']
export const TYPE_PRECEDENCE = ['Land', 'Creature', 'Planeswalker', 'Instant', 'Sorcery', 'Enchantment', 'Artifact']

export const ROLE_ORDER = ['ramp', 'draw', 'removal', 'noncreature_removal', 'wipe', 'counterspell', 'tutor', 'finisher', 'land', 'none']
export const ROLE_LABELS = {
  ramp: 'Ramp', draw: 'Card draw', removal: 'Creature removal',
  noncreature_removal: 'Other removal', wipe: 'Board wipes', counterspell: 'Counterspells',
  tutor: 'Tutors', finisher: 'Finishers', land: 'Lands', none: 'No measured role',
}

export const COLOR_ORDER = ['W', 'U', 'B', 'R', 'G', 'multi', 'colorless', 'land']
export const COLOR_LABELS = { W: 'White', U: 'Blue', B: 'Black', R: 'Red', G: 'Green', multi: 'Multicolor', colorless: 'Colorless', land: 'Lands' }

export function qty(card) {
  return Math.max(1, parseInt(card.quantity, 10) || 1)
}

export function nameKey(name) {
  return String(name || '').split(' // ')[0].trim().toLowerCase()
}

export function cardTypeLine(card) {
  return card.original_type_line || card.type_line || ''
}

export function primaryType(card) {
  const typeLine = cardTypeLine(card)
  for (const type of TYPE_PRECEDENCE) {
    if (typeLine.includes(type)) {
      return type
    }
  }
  return 'Other'
}

export function isLand(card) {
  return primaryType(card) === 'Land'
}

const WUBRG = ['W', 'U', 'B', 'R', 'G']

export function cardColors(card) {
  // Never sort card.colors in place: it is the deck's own state, shared with every tile.
  const found = new Set()
  if (Array.isArray(card.colors) && card.colors.length > 0) {
    for (const c of card.colors) found.add(String(c).toUpperCase())
  } else {
    for (const symbol of String(card.mana_cost || '').match(/\{[^}]*\}/g) || []) {
      for (const ch of symbol.toUpperCase()) found.add(ch)
    }
  }
  return WUBRG.filter(c => found.has(c))
}

export function cardManaValue(card) {
  const n = Number(card.cmc)
  if (card.cmc !== null && card.cmc !== undefined && card.cmc !== '' && Number.isFinite(n)) return n

  let value = 0
  for (const symbol of String(card.mana_cost || '').match(/\{[^}]*\}/g) || []) {
    const content = symbol.slice(1, -1).toUpperCase()
    if (/^\d+$/.test(content)) { value += parseInt(content, 10); continue }
    if (content === 'X' || content === 'Y' || content === 'Z') continue
    // A hybrid with a generic half ({2/W}) counts the larger half (CR 202.3f); every other
    // symbol -- coloured, hybrid ({W/U}), Phyrexian ({G/P}), {C}, {S} -- is one.
    const digits = content.split('/').filter(p => /^\d+$/.test(p)).map(p => parseInt(p, 10))
    value += digits.length ? Math.max(1, ...digits) : 1
  }
  return value
}

export function groupCards(cards, by, rolesByName) {
  if (!by) by = 'type'
  if (!cards || !Array.isArray(cards)) return []

  const result = []

  if (by === 'none') {
    const count = cards.reduce((sum, card) => sum + qty(card), 0)
    result.push({ key: 'all', label: 'All cards', cards, count })
    return result
  }

  if (by === 'type') {
    const typeGroups = {}
    for (const card of cards) {
      const type = primaryType(card)
      if (!typeGroups[type]) {
        typeGroups[type] = []
      }
      typeGroups[type].push(card)
    }

    for (const type of TYPE_ORDER) {
      if (typeGroups[type]) {
        const count = typeGroups[type].reduce((sum, card) => sum + qty(card), 0)
        const label = type === 'Creature' ? 'Creatures' : type === 'Instant' ? 'Instants' : type === 'Sorcery' ? 'Sorceries' :
                      type === 'Enchantment' ? 'Enchantments' : type === 'Artifact' ? 'Artifacts' : type === 'Planeswalker' ? 'Planeswalkers' :
                      type === 'Land' ? 'Lands' : type
        result.push({ key: type, label, cards: typeGroups[type], count })
      }
    }

    if (typeGroups['Other']) {
      result.push({ key: 'Other', label: 'Other', cards: typeGroups['Other'], count: typeGroups['Other'].reduce((sum, card) => sum + qty(card), 0) })
    }

    return result
  }

  if (by === 'color') {
    const colorGroups = {}
    for (const card of cards) {
      if (isLand(card)) {
        if (!colorGroups['land']) {
          colorGroups['land'] = []
        }
        colorGroups['land'].push(card)
        continue
      }

      const colors = cardColors(card)
      let key
      if (colors.length === 0) {
        key = 'colorless'
      } else if (colors.length === 1) {
        key = colors[0]
      } else {
        key = 'multi'
      }

      if (!colorGroups[key]) {
        colorGroups[key] = []
      }
      colorGroups[key].push(card)
    }

    for (const color of COLOR_ORDER) {
      if (colorGroups[color]) {
        result.push({ key: color, label: COLOR_LABELS[color], cards: colorGroups[color], count: colorGroups[color].reduce((sum, card) => sum + qty(card), 0) })
      }
    }

    return result
  }

  if (by === 'cmc') {
    const cmcGroups = {}
    for (const card of cards) {
      if (isLand(card)) {
        if (!cmcGroups['land']) {
          cmcGroups['land'] = []
        }
        cmcGroups['land'].push(card)
        continue
      }

      const value = cardManaValue(card)
      const bucket = Math.min(7, Math.floor(value))
      const key = bucket === 7 ? '7' : String(bucket)
      if (!cmcGroups[key]) {
        cmcGroups[key] = []
      }
      cmcGroups[key].push(card)
    }

    for (let i = 0; i <= 7; i++) {
      const key = String(i)
      const label = i === 7 ? 'MV 7+' : `MV ${i}`
      if (cmcGroups[key]) {
        result.push({ key, label, cards: cmcGroups[key], count: cmcGroups[key].reduce((sum, card) => sum + qty(card), 0) })
      }
    }

    if (cmcGroups['land']) {
      result.push({ key: 'land', label: 'Lands', cards: cmcGroups['land'], count: cmcGroups['land'].reduce((sum, card) => sum + qty(card), 0) })
    }

    return result
  }

  if (by === 'role') {
    if (!rolesByName) {
      const count = cards.reduce((sum, card) => sum + qty(card), 0)
      return [{ key: 'unmeasured', label: 'Roles not measured yet', cards, count }]
    }

    const roleGroups = {}
    for (const card of cards) {
      const nameKeyCard = nameKey(card.original_name)
      const roles = rolesByName[nameKeyCard] || []
      if (roles.length === 0) {
        if (!roleGroups['none']) {
          roleGroups['none'] = []
        }
        roleGroups['none'].push(card)
        continue
      }

      for (const role of roles) {
        if (!roleGroups[role]) {
          roleGroups[role] = []
        }
        roleGroups[role].push(card)
      }
    }

    const knownRoles = new Set(ROLE_ORDER)
    const unknownRoles = []

    for (const role in roleGroups) {
      if (!knownRoles.has(role)) {
        unknownRoles.push(role)
      }
    }

    for (const role of ROLE_ORDER) {
      if (role === 'none') continue   // pushed last, after any unknown roles
      if (roleGroups[role]) {
        const label = ROLE_LABELS[role]
        result.push({ key: role, label, cards: roleGroups[role], count: roleGroups[role].reduce((sum, card) => sum + qty(card), 0) })
      }
    }

    for (const role of unknownRoles) {
      const label = role.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
      result.push({ key: role, label, cards: roleGroups[role], count: roleGroups[role].reduce((sum, card) => sum + qty(card), 0) })
    }

    if (roleGroups['none']) {
      result.push({ key: 'none', label: ROLE_LABELS['none'], cards: roleGroups['none'], count: roleGroups['none'].reduce((sum, card) => sum + qty(card), 0) })
    }

    return result
  }

  return groupCards(cards, 'type', rolesByName)
}
