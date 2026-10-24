import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import farms from "../../../../../packages/schema/examples/farms.layer-schema.json";

import { fieldError, FormPreview, isRelevant } from "./FormPreview";
import type { SchemaDoc } from "./AttributeBuilder";

const schema = farms as unknown as SchemaDoc;

describe("FormPreview (shared evaluator)", () => {
  it("hides other_crop until crop = other, and shows the server-identical calculated area", async () => {
    render(<FormPreview schema={schema} geometryType="polygon" />);
    expect(screen.queryByText("Other crop")).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Main crop"), "other");
    expect(await screen.findByText("Other crop")).toBeInTheDocument();
    // area_ha = geom_area() div 10000 with the preview's 12345.6 m²
    expect(screen.getByText("1.23456")).toBeInTheDocument();
    expect(screen.getByText("no")).toBeInTheDocument(); // needs_polygon_for_eudr
  });

  it("evaluates relevant and constraint like the server", () => {
    const other = schema.fields.find((f) => f.key === "other_crop")!;
    expect(isRelevant(other, { crop: "cocoa" })).toBe(false);
    expect(isRelevant(other, { crop: "other" })).toBe(true);
    expect(fieldError(other, { crop: "other" })).toBe("Required");
    const year = schema.fields.find((f) => f.key === "planting_year")!;
    expect(fieldError(year, { planting_year: 2018 })).toBeNull();
  });
});
