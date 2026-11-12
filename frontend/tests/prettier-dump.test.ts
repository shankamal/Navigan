import { readFile } from "node:fs/promises";
import { describe, it } from "vitest";
import prettier from "prettier";

describe("temporary prettier dump", () => {
  it("prints canonical Upgrade Centre source", async () => {
    const source = await readFile(
      "src/modules/upgrade-management/live-upgrade-centre.tsx",
      "utf8",
    );
    const formatted = await prettier.format(source, {
      filepath: "src/modules/upgrade-management/live-upgrade-centre.tsx",
    });
    console.log("PRETTIER_DUMP_START");
    console.log(formatted);
    console.log("PRETTIER_DUMP_END");
  });
});
