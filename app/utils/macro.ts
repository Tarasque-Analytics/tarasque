import type { VolatilityRecord } from "./database";



export interface MacroSectors {
  xlk: VolatilityRecord[];
  xly: VolatilityRecord[];
  xlp: VolatilityRecord[];
  xle: VolatilityRecord[];
  xlf: VolatilityRecord[];
  xlv: VolatilityRecord[];
  xli: VolatilityRecord[];
  xlb: VolatilityRecord[];
  xlre: VolatilityRecord[];
  xlu: VolatilityRecord[];
}

export interface MacroPayload {
  sectors: MacroSectors;
  ticker
}

export function loadMacroSectorData() {

}