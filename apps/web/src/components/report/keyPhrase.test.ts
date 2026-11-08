import { describe, expect, it } from "vitest";
import { keyPhrase } from "./CellReport";

describe("keyPhrase (gold underline target)", () => {
  it("underlines the phrase after the comma, before 'within'", () => {
    expect(keyPhrase("Plenty of people, few pharmacies within a 10-minute walk.")).toEqual([
      "Plenty of people, ",
      "few pharmacies",
      " within a 10-minute walk.",
    ]);
  });
  it("underlines up to a colon", () => {
    expect(keyPhrase("Already well served: 14 pharmacies within a 10-minute walk.")[1]).toBe("Already well served");
  });
  it("falls back to the first words", () => {
    const [b, k, a] = keyPhrase("We need more data here before we say anything.");
    expect(b + k + a).toBe("We need more data here before we say anything.");
    expect(k).toBe("We need more");
  });
});
