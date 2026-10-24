import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { api } from "@/api/client";
import { errorMessage } from "@/api/hooks";
import { useSession } from "@/auth/session";
import { Alert, Button, Field, Input } from "@/components/ui";
import { t } from "@/lib/strings";

const passwordSchema = z.object({ identifier: z.string().min(3), password: z.string().min(1) });
const otpRequestSchema = z.object({ destination: z.string().min(3) });
const otpVerifySchema = z.object({
  destination: z.string().min(3),
  code: z.string().regex(/^\d{4,8}$/),
});

export function LoginPage() {
  const [mode, setMode] = useState<"password" | "otp">("password");
  return (
    <main className="flex min-h-full items-center justify-center bg-neutral-100 p-4">
      <div className="w-full max-w-sm rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
        <h1 className="mb-1 text-xl font-semibold">{t.appName}</h1>
        <p className="mb-5 text-sm text-neutral-600">{t.login.title}</p>
        {mode === "password" ? <PasswordForm /> : <OtpForm />}
        <button
          type="button"
          className="mt-4 text-sm text-brand-700 hover:underline"
          onClick={() => setMode(mode === "password" ? "otp" : "password")}
        >
          {mode === "password" ? t.login.useOtp : t.login.usePassword}
        </button>
      </div>
    </main>
  );
}

function PasswordForm() {
  const { afterLogin } = useSession();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof passwordSchema>>({ resolver: zodResolver(passwordSchema) });
  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      await api.login(values.identifier, values.password);
      await afterLogin();
      await navigate({ to: "/" });
    } catch (e) {
      setError(errorMessage(e));
    }
  });
  return (
    <form onSubmit={onSubmit} className="space-y-3" noValidate>
      <Field label={t.login.identifier} error={form.formState.errors.identifier?.message}>
        <Input autoComplete="username" {...form.register("identifier")} />
      </Field>
      <Field label={t.login.password} error={form.formState.errors.password?.message}>
        <Input type="password" autoComplete="current-password" {...form.register("password")} />
      </Field>
      {error && <Alert>{error}</Alert>}
      <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
        {t.login.submit}
      </Button>
    </form>
  );
}

function OtpForm() {
  const { afterLogin } = useSession();
  const navigate = useNavigate();
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const request = useForm<z.infer<typeof otpRequestSchema>>({
    resolver: zodResolver(otpRequestSchema),
  });
  const verify = useForm<z.infer<typeof otpVerifySchema>>({
    resolver: zodResolver(otpVerifySchema),
  });

  if (!sent) {
    return (
      <form
        className="space-y-3"
        noValidate
        onSubmit={request.handleSubmit(async (v) => {
          setError(null);
          try {
            await api.post("/api/v1/auth/otp/request", { body: { destination: v.destination } });
            verify.setValue("destination", v.destination);
            setSent(v.destination);
          } catch (e) {
            setError(errorMessage(e));
          }
        })}
      >
        <Field label={t.login.identifier} error={request.formState.errors.destination?.message}>
          <Input {...request.register("destination")} />
        </Field>
        {error && <Alert>{error}</Alert>}
        <Button type="submit" className="w-full">
          {t.login.requestCode}
        </Button>
      </form>
    );
  }
  return (
    <form
      className="space-y-3"
      noValidate
      onSubmit={verify.handleSubmit(async (v) => {
        setError(null);
        try {
          await api.verifyOtp(v.destination, v.code);
          await afterLogin();
          await navigate({ to: "/" });
        } catch (e) {
          setError(errorMessage(e));
        }
      })}
    >
      <Alert tone="info">{t.login.otpSent}</Alert>
      <Field label={t.login.code} error={verify.formState.errors.code?.message}>
        <Input inputMode="numeric" autoComplete="one-time-code" {...verify.register("code")} />
      </Field>
      {error && <Alert>{error}</Alert>}
      <Button type="submit" className="w-full">
        {t.login.verify}
      </Button>
    </form>
  );
}
