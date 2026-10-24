import { useState } from "react";

import { Button, Dialog, Field } from "@/components/ui";

/** Paste a JSON document (e.g. one of packages/schema/examples) into an editor. */
export function ImportJson({
  label,
  onImport,
}: {
  label: string;
  onImport: (doc: Record<string, unknown>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <Button type="button" variant="secondary" onClick={() => setOpen(true)}>
        Import JSON
      </Button>
      <Dialog open={open} onOpenChange={setOpen} title={`Import ${label.toLowerCase()}`}>
        <Field
          label={label}
          error={error ?? undefined}
          hint="Paste a document, e.g. one of packages/schema/examples"
        >
          <textarea
            className="h-48 w-full rounded-md border border-neutral-300 p-2 font-mono text-xs"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </Field>
        <div className="mt-3 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => {
              try {
                const doc = JSON.parse(text) as Record<string, unknown>;
                onImport(doc);
                setOpen(false);
                setText("");
                setError(null);
              } catch {
                setError("Not valid JSON");
              }
            }}
          >
            Import
          </Button>
        </div>
      </Dialog>
    </>
  );
}
