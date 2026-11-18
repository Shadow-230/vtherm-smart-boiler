// The page's texts, in Home Assistant's language (CLAUDE.md: the plugin has no language of its
// own). English is the source; the files live beside the built page, where the plugin also reads
// the sidebar title from them.
import en from "../../custom_components/vtherm_smart_boiler/frontend/translations/en.json";
import pl from "../../custom_components/vtherm_smart_boiler/frontend/translations/pl.json";

export interface Texts {
  [key: string]: string | Texts;
}

export const LANGUAGES: Readonly<Record<string, Texts>> = { en, pl };

/** The texts for a language code: "pl-PL" falls back to "pl", an unknown one to English. */
export function textsFor(language: string | undefined): Texts {
  if (!language) return LANGUAGES.en;
  const code = language.toLowerCase();
  return LANGUAGES[code] ?? LANGUAGES[code.split("-")[0]] ?? LANGUAGES.en;
}

function lookup(texts: Texts, key: string): string | undefined {
  let node: string | Texts | undefined = texts;
  for (const part of key.split(".")) {
    if (typeof node !== "object") return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

/** The text of `key` ("panel.title") in `language`, else in English, else the key itself. */
export function localize(language: string | undefined, key: string): string {
  return lookup(textsFor(language), key) ?? lookup(LANGUAGES.en, key) ?? key;
}

/** Every key of a text tree, dotted ("panel.title"). */
export function keysOf(texts: Texts, prefix = ""): string[] {
  return Object.entries(texts).flatMap(([name, value]) =>
    typeof value === "string" ? [`${prefix}${name}`] : keysOf(value, `${prefix}${name}.`),
  );
}
