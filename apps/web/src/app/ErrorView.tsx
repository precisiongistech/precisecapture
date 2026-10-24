import { ApiError } from "@precisecapture/api-client";

import { Alert, Button } from "@/components/ui";
import { t } from "@/lib/strings";

export function ErrorView({ error, reset }: { error: unknown; reset?: () => void }) {
  const detail =
    error instanceof ApiError
      ? `${error.problem.title}${error.problem.detail ? `: ${error.problem.detail}` : ""}`
      : error instanceof Error
        ? error.message
        : t.common.error;
  return (
    <div className="space-y-3 p-6">
      <Alert>{detail}</Alert>
      {reset && (
        <Button variant="secondary" onClick={reset}>
          {t.common.retry}
        </Button>
      )}
    </div>
  );
}
