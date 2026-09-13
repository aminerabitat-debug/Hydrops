// Localisation approximative par adresse IP (consigne utilisateur : "Zoomer la carte lors du
// démarrage selon l'adresse IP de connexion") — sert uniquement a centrer la carte au demarrage
// avant qu'un projet/trace ne soit charge, jamais une geolocalisation precise (resolution ville,
// cf. les services eux-memes). Cascade de services publics gratuits, sans cle (meme principe que
// hydrops_api.services.crossings : une seule source n'est pas fiable a elle seule), chacun avec sa
// propre forme de reponse.
export interface ApproxIpLocation {
  lat: number
  lon: number
}

const REQUEST_TIMEOUT_MS = 4000

interface IpGeolocationSource {
  url: string
  parse: (data: unknown) => ApproxIpLocation | null
}

const IP_GEOLOCATION_SOURCES: IpGeolocationSource[] = [
  {
    url: 'https://get.geojs.io/v1/ip/geo.json',
    parse: (data) => {
      const d = data as { latitude?: string; longitude?: string }
      const lat = Number(d.latitude)
      const lon = Number(d.longitude)
      return Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null
    },
  },
  {
    url: 'https://ipwho.is/',
    parse: (data) => {
      const d = data as { success?: boolean; latitude?: number; longitude?: number }
      if (!d.success) return null
      const lat = Number(d.latitude)
      const lon = Number(d.longitude)
      return Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null
    },
  },
  {
    url: 'https://ipinfo.io/json',
    parse: (data) => {
      const d = data as { loc?: string }
      if (!d.loc) return null
      const [lat, lon] = d.loc.split(',').map(Number)
      return Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null
    },
  },
]

async function fetchWithTimeout(url: string): Promise<Response> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    return await fetch(url, { signal: controller.signal })
  } finally {
    clearTimeout(timeout)
  }
}

// `null` si tous les services echouent (reseau, quota, CORS) — l'appelant garde alors le centrage
// par defaut, jamais bloquant.
export async function fetchApproximateLocationFromIp(): Promise<ApproxIpLocation | null> {
  for (const source of IP_GEOLOCATION_SOURCES) {
    try {
      const response = await fetchWithTimeout(source.url)
      if (!response.ok) continue
      const location = source.parse(await response.json())
      if (location) return location
    } catch {
      continue
    }
  }
  return null
}
