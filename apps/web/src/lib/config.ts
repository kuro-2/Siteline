/** Public runtime config. Rename the app by changing NEXT_PUBLIC_APP_NAME (one line). */
export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || "Nukkad";
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(
  /\/$/,
  "",
);
export const MAP_STYLE_URL =
  process.env.NEXT_PUBLIC_MAP_STYLE_URL || "https://tiles.openfreemap.org/styles/positron";
export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
export const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
export const DEFAULT_AREA = process.env.NEXT_PUBLIC_DEFAULT_AREA || "pilot";
export const PHONE_OTP_ENABLED = process.env.NEXT_PUBLIC_PHONE_OTP_ENABLED === "true";
export const TIME_ZONE = "Asia/Kolkata";
