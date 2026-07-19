// Shared transport colour scheme for the itinerary map segments and the
// step badges, so both stay in sync. MRT lines use the official network
// colours; buses are cyan; driving keeps the gold-ish tone; walking is green
// (drawn dashed on the map to separate it from the green East-West line).

export const MRT_LINE_COLORS: Record<string, string> = {
  NS: '#D42E12', // North South Line — red
  EW: '#009645', // East West Line — green
  CG: '#009645', // Changi Airport branch — green
  NE: '#9900AA', // North East Line — purple
  CC: '#FF9E18', // Circle Line — orange
  CE: '#FF9E18', // Circle Line extension — orange
  DT: '#005EC4', // Downtown Line — blue
  TE: '#9D5B25', // Thomson–East Coast Line — brown
  BP: '#748477', // Bukit Panjang LRT — grey
  SK: '#748477', // Sengkang LRT — grey
  PG: '#748477', // Punggol LRT — grey
  JR: '#0099AA', // Jurong Region Line — teal
  CR: '#97C616', // Cross Island Line — light green
}

export const BUS_COLOR = '#00A5C4'   // cyan
export const WALK_COLOR = '#2F7D4A'  // green (dashed on the map)
export const DRIVE_COLOR = '#8A5324' // gold-ish (unchanged)
export const PT_COLOR = '#2563A6'    // generic transit fallback (no line detail)

/** Two-letter MRT line code for a service string, if it maps to a known line. */
export function mrtLineCode(service?: string | null): string | null {
  if (!service) return null
  const match = String(service).trim().toUpperCase().match(/^[A-Z]{2}/)
  return match && MRT_LINE_COLORS[match[0]] ? match[0] : null
}

/** Colour for a transport mode + service, shared by the map and the badges. */
export function stepColor(mode: string, service?: string | null): string {
  switch ((mode || '').toLowerCase()) {
    case 'walk':
      return WALK_COLOR
    case 'bus':
      return BUS_COLOR
    case 'drive':
      return DRIVE_COLOR
    case 'subway':
    case 'rail':
    case 'tram':
    case 'pt': {
      const code = mrtLineCode(service)
      return code ? MRT_LINE_COLORS[code] : PT_COLOR
    }
    default:
      return PT_COLOR
  }
}
