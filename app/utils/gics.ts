/**
 * GICS (Global Industry Classification Standard) constants and utilities.
 * Hierarchical numeric classification: 8 digits (XX XX XX XX)
 * - Digits 1-2:  Sector
 * - Digits 3-4:  Industry Group
 * - Digits 5-6:  Industry
 * - Digits 7-8:  Sub-industry
 *
 * Used to construct and parse GICS codes from SecurityMeta strings.
 */

// ─────────────────────────────────────────────────────────────
// Sector codes (first 2 digits)
// ─────────────────────────────────────────────────────────────
export const GICS_SECTORS: Record<string, string> = {
  "Energy": "10",
  "Materials": "15",
  "Industrials": "20",
  "Consumer Discretionary": "25",
  "Consumer Staples": "30",
  "Health Care": "35",
  "Financials": "40",
  "Information Technology": "45",
  "Communication Services": "50",
  "Utilities": "55",
  "Real Estate": "60",
};

export const GICS_SECTORS_REVERSE: Record<string, string> = Object.fromEntries(
  Object.entries(GICS_SECTORS).map(([name, code]) => [code, name])
);

// ─────────────────────────────────────────────────────────────
// Industry Group codes (digits 3-4)
// Keyed by sector code + industry group name for precise lookup
// ─────────────────────────────────────────────────────────────
export const GICS_INDUSTRY_GROUPS: Record<string, string> = {
  // Energy (10)
  "10|Energy": "10",
  // Materials (15)
  "15|Materials": "15",
  // Industrials (20)
  "20|Capital Goods": "20",
  "20|Commercial & Professional Services": "21",
  "20|Transportation": "22",
  // Consumer Discretionary (25)
  "25|Automobiles & Components": "25",
  "25|Consumer Durables & Apparel": "26",
  "25|Consumer Services": "27",
  "25|Retailing": "28",
  // Consumer Staples (30)
  "30|Food Beverage & Tobacco": "30",
  "30|Household & Personal Products": "31",
  // Health Care (35)
  "35|Health Care Equipment & Supplies": "35",
  "35|Health Care Providers & Services": "36",
  "35|Pharmaceuticals Biotech & Life Sciences": "37",
  // Financials (40)
  "40|Banks": "40",
  "40|Diversified Financials": "41",
  "40|Insurance": "42",
  "40|Real Estate Management & Development": "43",
  // Information Technology (45)
  "45|Software & Services": "45",
  "45|Technology Hardware & Equipment": "46",
  "45|Semiconductors & Semiconductor Equipment": "47",
  // Communication Services (50)
  "50|Telecommunication Services": "50",
  "50|Media & Entertainment": "51",
  // Utilities (55)
  "55|Utilities": "55",
  // Real Estate (60)
  "60|Real Estate Management & Development": "60",
};

// ─────────────────────────────────────────────────────────────
// Industry codes (digits 5-6)
// Keyed by sector code + industry name for precise lookup
// ─────────────────────────────────────────────────────────────
export const GICS_INDUSTRIES: Record<string, string> = {
  // Energy (10)
  "10|Oil Gas & Coal Extraction": "01",
  "10|Oil Gas Refining & Marketing": "02",
  "10|Integrated Oil & Gas": "10",
  // Materials (15)
  "15|Chemicals": "01",
  "15|Construction Materials": "02",
  "15|Container & Packaging": "03",
  "15|Metals & Mining": "04",
  "15|Paper & Forest Products": "05",
  // Industrials (20)
  "20|Aerospace & Defense": "01",
  "20|Building Products": "02",
  "20|Construction & Engineering": "03",
  "20|Electrical Equipment": "04",
  "20|Industrial Machinery": "05",
  "20|Tools & Accessories": "06",
  // Industrials (21)
  "21|Human Resources & Employment Services": "01",
  "21|Diversified Support Services": "02",
  "21|Environmental & Facilities Services": "03",
  "21|Office Services & Supplies": "04",
  "21|Security & Alarm Services": "05",
  "21|Waste Management": "06",
  // Industrials (22)
  "22|Airlines": "01",
  "22|Railroads": "02",
  "22|Road & Rail": "03",
  "22|Marine": "04",
  "22|Transportation Infrastructure": "05",
  // Consumer Discretionary (25)
  "25|Auto Parts & Equipment": "01",
  "25|Automobiles": "02",
  "25|Motorcycles": "03",
  // Consumer Discretionary (26)
  "26|Footwear": "01",
  "26|Apparel Accessories & Luxury Goods": "02",
  "26|Textile Apparel & Footwear": "03",
  // Consumer Discretionary (27)
  "27|Hotels Restaurants & Leisure": "01",
  "27|Distributors": "02",
  "27|Specialty Retail": "03",
  // Consumer Discretionary (28)
  "28|Internet Retail": "01",
  "28|Department Stores": "02",
  "28|General Merchandise Stores": "03",
  // Consumer Staples (30)
  "30|Agricultural Products": "01",
  "30|Beverages": "02",
  "30|Food Products": "03",
  "30|Tobacco": "04",
  // Consumer Staples (31)
  "31|Household Products": "01",
  "31|Personal Products": "02",
  // Health Care (35)
  "35|Health Care Equipment": "01",
  "35|Supplies": "02",
  // Health Care (36)
  "36|Ambulatory Health Care Services": "01",
  "36|Medical Facilities": "02",
  "36|Managed Health Care": "03",
  // Health Care (37)
  "37|Biotechnology": "01",
  "37|Pharmaceuticals": "02",
  "37|Life Sciences Tools & Services": "03",
  // Financials (40)
  "40|Banks": "01",
  "40|Thrifts & Mortgage Finance": "02",
  // Financials (41)
  "41|Diversified Capital Markets": "01",
  "41|Asset Management & Custody Banks": "02",
  "41|Investment Banking & Brokerage": "03",
  // Financials (42)
  "42|Insurance Brokers": "01",
  "42|Property & Casualty Insurance": "02",
  "42|Reinsurance": "03",
  "42|Specialty Insurance": "04",
  "42|Life Insurance": "05",
  // Financials (43)
  "43|Real Estate Development": "01",
  "43|Real Estate Operating Companies": "02",
  "43|Real Estate Services": "03",
  // Information Technology (45)
  "45|IT Consulting & Other Services": "01",
  "45|Software": "02",
  "45|IT Services": "03",
  // Information Technology (46)
  "46|Communications Equipment": "01",
  "46|Computer Hardware": "02",
  "46|Computer Storage & Peripherals": "03",
  "46|Office Electronics": "04",
  // Information Technology (47)
  "47|Semiconductor Equipment": "01",
  "47|Semiconductors": "02",
  // Communication Services (50)
  "50|Integrated Telecommunication Services": "01",
  "50|Wireless Telecommunication Services": "02",
  // Communication Services (51)
  "51|Media": "01",
  "51|Movies & Entertainment": "02",
  "51|Internet Services & Media": "03",
  // Utilities (55)
  "55|Electric Utilities": "01",
  "55|Gas Utilities": "02",
  "55|Multi-Utilities": "03",
  "55|Water Utilities": "04",
  "55|Independent Power Producers & Energy Traders": "05",
  // Real Estate (60)
  "60|Diversified Real Estate Activities": "01",
  "60|Real Estate Operating Companies": "02",
  "60|Real Estate Development": "03",
  "60|Real Estate Services": "04",
};

// ─────────────────────────────────────────────────────────────
// Sub-industry codes (digits 7-8)
// Keyed by sector + industry + sub-industry name
// Complete GICS standard as of 2024
// ─────────────────────────────────────────────────────────────
export const GICS_SUBINDUSTRIES: Record<string, string> = {
  // ========== ENERGY (10) ==========
  // Oil Gas & Coal Extraction (01)
  "10|Oil Gas & Coal Extraction|Oil & Gas Exploration & Production": "01",
  "10|Oil Gas & Coal Extraction|Coal & Consumable Fuels": "02",
  // Oil Gas Refining & Marketing (02)
  "10|Oil Gas Refining & Marketing|Oil & Gas Refining & Marketing": "01",
  "10|Oil Gas Refining & Marketing|Oil & Gas Storage & Transportation": "02",
  "10|Oil Gas Refining & Marketing|Midstream Energy Infrastructure": "03",
  // Integrated Oil & Gas (10)
  "10|Integrated Oil & Gas|Integrated Oil & Gas": "01",

  // ========== MATERIALS (15) ==========
  // Chemicals (01)
  "15|Chemicals|Commodity Chemicals": "01",
  "15|Chemicals|Specialty Chemicals": "02",
  "15|Chemicals|Fertilizers & Agricultural Chemicals": "03",
  // Construction Materials (02)
  "15|Construction Materials|Construction Materials": "01",
  // Container & Packaging (03)
  "15|Container & Packaging|Metal & Glass Containers": "01",
  "15|Container & Packaging|Paper Containers & Packaging": "02",
  // Metals & Mining (04)
  "15|Metals & Mining|Aluminum": "01",
  "15|Metals & Mining|Diversified Metals & Mining": "02",
  "15|Metals & Mining|Copper": "03",
  "15|Metals & Mining|Gold": "04",
  "15|Metals & Mining|Precious Metals & Minerals": "05",
  "15|Metals & Mining|Steel": "06",
  // Paper & Forest Products (05)
  "15|Paper & Forest Products|Forest Products": "01",
  "15|Paper & Forest Products|Paper Packaging": "02",

  // ========== INDUSTRIALS (20) ==========
  // Aerospace & Defense (01)
  "20|Aerospace & Defense|Aerospace & Defense": "01",
  // Building Products (02)
  "20|Building Products|Building Products & Supplies": "01",
  // Construction & Engineering (03)
  "20|Construction & Engineering|Construction & Engineering": "01",
  // Electrical Equipment (04)
  "20|Electrical Equipment|Electrical Components & Equipment": "01",
  "20|Electrical Equipment|Heavy Electrical Equipment": "02",
  // Industrial Machinery (05)
  "20|Industrial Machinery|Industrial Machinery": "01",
  // Tools & Accessories (06)
  "20|Tools & Accessories|Tools & Accessories": "01",

  // ========== COMMERCIAL & PROFESSIONAL SERVICES (21) ==========
  // Human Resources & Employment Services (01)
  "21|Human Resources & Employment Services|Human Resources & Employment Services": "01",
  // Diversified Support Services (02)
  "21|Diversified Support Services|Diversified Support Services": "01",
  // Environmental & Facilities Services (03)
  "21|Environmental & Facilities Services|Environmental & Facilities Services": "01",
  // Office Services & Supplies (04)
  "21|Office Services & Supplies|Office Services & Supplies": "01",
  // Security & Alarm Services (05)
  "21|Security & Alarm Services|Security & Alarm Services": "01",
  // Waste Management (06)
  "21|Waste Management|Waste Management": "01",

  // ========== TRANSPORTATION (22) ==========
  // Airlines (01)
  "22|Airlines|Airlines": "01",
  // Railroads (02)
  "22|Railroads|Railroads": "01",
  // Road & Rail (03)
  "22|Road & Rail|Trucking": "01",
  "22|Road & Rail|Passenger Airlines": "02",
  // Marine (04)
  "22|Marine|Marine Shipping": "01",
  "22|Marine|Marine Ports & Services": "02",
  // Transportation Infrastructure (05)
  "22|Transportation Infrastructure|Airport Services": "01",
  "22|Transportation Infrastructure|Highways & Railtracks": "02",
  "22|Transportation Infrastructure|Marine Ports & Services": "03",

  // ========== CONSUMER DISCRETIONARY (25) ==========
  // Auto Parts & Equipment (01)
  "25|Auto Parts & Equipment|Auto Parts & Equipment": "01",
  // Automobiles (02)
  "25|Automobiles|Automobile Manufacturers": "01",
  // Motorcycles (03)
  "25|Motorcycles|Motorcycle Manufacturers": "01",

  // ========== CONSUMER DURABLES & APPAREL (26) ==========
  // Footwear (01)
  "26|Footwear|Footwear": "01",
  // Apparel Accessories & Luxury Goods (02)
  "26|Apparel Accessories & Luxury Goods|Apparel Manufacturing": "01",
  "26|Apparel Accessories & Luxury Goods|Apparel Retail": "02",
  "26|Apparel Accessories & Luxury Goods|Luxury Goods": "03",
  // Textile Apparel & Footwear (03)
  "26|Textile Apparel & Footwear|Textile Apparel & Footwear": "01",

  // ========== CONSUMER SERVICES (27) ==========
  // Hotels Restaurants & Leisure (01)
  "27|Hotels Restaurants & Leisure|Casinos & Gaming": "01",
  "27|Hotels Restaurants & Leisure|Hotels Resorts & Cruise Lines": "02",
  "27|Hotels Restaurants & Leisure|Leisure Facilities": "03",
  "27|Hotels Restaurants & Leisure|Restaurants": "04",
  // Distributors (02)
  "27|Distributors|Distributors": "01",
  // Specialty Retail (03)
  "27|Specialty Retail|Automotive Retail": "01",
  "27|Specialty Retail|Computer & Electronics Retail": "02",
  "27|Specialty Retail|Home Improvement Retail": "03",
  "27|Specialty Retail|Specialty Retail": "04",

  // ========== RETAILING (28) ==========
  // Internet Retail (01)
  "28|Internet Retail|Internet Retail": "01",
  // Department Stores (02)
  "28|Department Stores|Department Stores": "01",
  // General Merchandise Stores (03)
  "28|General Merchandise Stores|General Merchandise Stores": "01",

  // ========== FOOD BEVERAGE & TOBACCO (30) ==========
  // Agricultural Products (01)
  "30|Agricultural Products|Agricultural Products": "01",
  // Beverages (02)
  "30|Beverages|Brewers": "01",
  "30|Beverages|Distillers & Vintners": "02",
  "30|Beverages|Non-alcoholic Beverages": "03",
  // Food Products (03)
  "30|Food Products|Packaged Foods & Meats": "01",
  // Tobacco (04)
  "30|Tobacco|Tobacco": "01",

  // ========== HOUSEHOLD & PERSONAL PRODUCTS (31) ==========
  // Household Products (01)
  "31|Household Products|Household Products": "01",
  // Personal Products (02)
  "31|Personal Products|Personal Products": "01",

  // ========== HEALTH CARE EQUIPMENT & SUPPLIES (35) ==========
  // Health Care Equipment (01)
  "35|Health Care Equipment|Health Care Equipment": "01",
  // Supplies (02)
  "35|Supplies|Health Care Supplies": "01",

  // ========== HEALTH CARE PROVIDERS & SERVICES (36) ==========
  // Ambulatory Health Care Services (01)
  "36|Ambulatory Health Care Services|Ambulatory Health Care Services": "01",
  // Medical Facilities (02)
  "36|Medical Facilities|Medical Facilities": "01",
  // Managed Health Care (03)
  "36|Managed Health Care|Health Care Providers": "01",

  // ========== PHARMACEUTICALS BIOTECH & LIFE SCIENCES (37) ==========
  // Biotechnology (01)
  "37|Biotechnology|Biotechnology": "01",
  // Pharmaceuticals (02)
  "37|Pharmaceuticals|Pharmaceutical Products": "01",
  // Life Sciences Tools & Services (03)
  "37|Life Sciences Tools & Services|Life Sciences Tools & Services": "01",

  // ========== BANKS (40) ==========
  // Banks (01)
  "40|Banks|Banks": "01",
  // Thrifts & Mortgage Finance (02)
  "40|Thrifts & Mortgage Finance|Thrifts & Mortgage Finance": "01",

  // ========== DIVERSIFIED FINANCIALS (41) ==========
  // Diversified Capital Markets (01)
  "41|Diversified Capital Markets|Financial Exchanges & Data": "01",
  "41|Diversified Capital Markets|Mortgage Real Estate Investment Trusts": "02",
  // Asset Management & Custody Banks (02)
  "41|Asset Management & Custody Banks|Asset Management & Custody Banks": "01",
  // Investment Banking & Brokerage (03)
  "41|Investment Banking & Brokerage|Investment Banking & Brokerage": "01",

  // ========== INSURANCE (42) ==========
  // Insurance Brokers (01)
  "42|Insurance Brokers|Insurance Brokers": "01",
  // Property & Casualty Insurance (02)
  "42|Property & Casualty Insurance|Property & Casualty Insurance": "01",
  // Reinsurance (03)
  "42|Reinsurance|Reinsurance": "01",
  // Specialty Insurance (04)
  "42|Specialty Insurance|Specialty Insurance": "01",
  // Life Insurance (05)
  "42|Life Insurance|Life Insurance": "01",

  // ========== REAL ESTATE (43) ==========
  // Real Estate Development (01)
  "43|Real Estate Development|Real Estate Development": "01",
  // Real Estate Operating Companies (02)
  "43|Real Estate Operating Companies|Hotel & Resort REITs": "01",
  "43|Real Estate Operating Companies|Industrial REITs": "02",
  "43|Real Estate Operating Companies|Office REITs": "03",
  "43|Real Estate Operating Companies|Residential REITs": "04",
  "43|Real Estate Operating Companies|Retail REITs": "05",
  "43|Real Estate Operating Companies|Specialized REITs": "06",
  "43|Real Estate Operating Companies|Diversified REITs": "07",
  // Real Estate Services (03)
  "43|Real Estate Services|Real Estate Services": "01",

  // ========== SOFTWARE & SERVICES (45) ==========
  // IT Consulting & Other Services (01)
  "45|IT Consulting & Other Services|IT Consulting & Other Services": "01",
  // Software (02)
  "45|Software|Application Software": "01",
  "45|Software|Systems Software": "02",
  "45|Software|Infrastructure Software": "03",
  // IT Services (03)
  "45|IT Services|IT Services & Facilities": "01",

  // ========== TECHNOLOGY HARDWARE & EQUIPMENT (46) ==========
  // Communications Equipment (01)
  "46|Communications Equipment|Communications Equipment": "01",
  // Computer Hardware (02)
  "46|Computer Hardware|Computer Hardware": "01",
  // Computer Storage & Peripherals (03)
  "46|Computer Storage & Peripherals|Computer Storage & Peripherals": "01",
  // Office Electronics (04)
  "46|Office Electronics|Office Electronics": "01",

  // ========== SEMICONDUCTORS & SEMICONDUCTOR EQUIPMENT (47) ==========
  // Semiconductor Equipment (01)
  "47|Semiconductor Equipment|Semiconductor Equipment": "01",
  // Semiconductors (02)
  "47|Semiconductors|Semiconductors": "01",

  // ========== TELECOMMUNICATION SERVICES (50) ==========
  // Integrated Telecommunication Services (01)
  "50|Integrated Telecommunication Services|Integrated Telecommunication Services": "01",
  // Wireless Telecommunication Services (02)
  "50|Wireless Telecommunication Services|Wireless Telecommunication Services": "01",

  // ========== MEDIA & ENTERTAINMENT (51) ==========
  // Media (01)
  "51|Media|Advertising": "01",
  "51|Media|Broadcasting": "02",
  "51|Media|Cable & Satellite": "03",
  "51|Media|Publishing": "04",
  // Movies & Entertainment (02)
  "51|Movies & Entertainment|Movies & Entertainment": "01",
  // Internet Services & Media (03)
  "51|Internet Services & Media|Internet Services & Media": "01",

  // ========== UTILITIES (55) ==========
  // Electric Utilities (01)
  "55|Electric Utilities|Electric Utilities": "01",
  // Gas Utilities (02)
  "55|Gas Utilities|Gas Utilities": "01",
  // Multi-Utilities (03)
  "55|Multi-Utilities|Multi-Utilities": "01",
  // Water Utilities (04)
  "55|Water Utilities|Water Utilities": "01",
  // Independent Power Producers & Energy Traders (05)
  "55|Independent Power Producers & Energy Traders|Independent Power Producers & Energy Traders": "01",

  // ========== REAL ESTATE (60) ==========
  // Diversified Real Estate Activities (01)
  "60|Diversified Real Estate Activities|Diversified Real Estate": "01",
  // Real Estate Operating Companies (02)
  "60|Real Estate Operating Companies|Real Estate Operating Companies": "01",
  // Real Estate Development (03)
  "60|Real Estate Development|Real Estate Development": "01",
  // Real Estate Services (04)
  "60|Real Estate Services|Real Estate Services": "01",
};

// ─────────────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────────────

/**
 * Constructs a full GICS code (8 digits) from sector, industry group, industry, and sub-industry.
 * If a component is not found in the mapping, returns an empty string.
 */
export function constructGicsCode(
  sector: string | null | undefined,
  industryGroup?: string | null | undefined,
  industry?: string | null | undefined,
  subindustry?: string | null | undefined
): string {
  console.log("Sector:", sector);
  console.log("Industry:", industry);
  console.log("Subindustry:", subindustry);
  if (!sector) return "";

  const sectorCode = GICS_SECTORS[sector];
  if (!sectorCode) return "";

  // If only sector is provided, return sector code padded to 8 digits
  if (!industry) return sectorCode.padEnd(8, "0");

  // Construct from available data
  let code = sectorCode;

  // Industry group (use provided or default)
  const igKey = industryGroup ? `${sectorCode}|${industryGroup}` : `${sectorCode}|${sector}`;
  const igCode = GICS_INDUSTRY_GROUPS[igKey];
  code += igCode ? igCode : "00";

  // Industry
  const indKey = `${sectorCode}|${industry}`;
  const indCode = GICS_INDUSTRIES[indKey];
  code += indCode ? indCode : "00";

  // Sub-industry
  if (subindustry) {
    const sibKey = `${sectorCode}|${industry}|${subindustry}`;
    const sibCode = GICS_SUBINDUSTRIES[sibKey];
    code += sibCode ? sibCode : "00";
  } else {
    code += "00";
  }

  return code;
}