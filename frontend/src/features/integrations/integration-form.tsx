"use client";

import { useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { TextareaField } from "@/components/ui/textarea";
import {
  CREATABLE_PROVIDERS,
  EMPTY_FORM,
  PROVIDER_LABELS,
  type CreatableProvider,
  type IntegrationFormValues,
} from "@/features/integrations/integration-form-model";

type Props = {
  mode: "create" | "edit";
  initial?: IntegrationFormValues;
  pending: boolean;
  error: unknown;
  onSubmit: (values: IntegrationFormValues) => void;
  onCancel: () => void;
};

/**
 * Adds an integration or edits its settings. The secret box exists only when adding: after that,
 * a secret is replaced from its own form, because it can never be shown or edited in place.
 */
export function IntegrationForm({ mode, initial, pending, error, onSubmit, onCancel }: Props) {
  const [values, setValues] = useState<IntegrationFormValues>(initial ?? EMPTY_FORM);
  const [nameError, setNameError] = useState<string | null>(null);
  const idPrefix = mode === "create" ? "new-integration" : "edit-integration";

  function set<K extends keyof IntegrationFormValues>(key: K, value: IntegrationFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (values.name.trim().length < 2) {
          setNameError("Give it a name of at least 2 characters.");
          return;
        }
        setNameError(null);
        onSubmit({ ...values, name: values.name.trim() });
      }}
    >
      {mode === "create" && (
        <div className="space-y-1.5">
          <label htmlFor={`${idPrefix}-provider`} className="text-sm font-medium">
            Type
          </label>
          <Select
            id={`${idPrefix}-provider`}
            className="w-full"
            value={values.provider}
            onChange={(event) => set("provider", event.target.value as CreatableProvider)}
          >
            {CREATABLE_PROVIDERS.map((provider) => (
              <option key={provider} value={provider}>
                {PROVIDER_LABELS[provider]}
              </option>
            ))}
          </Select>
        </div>
      )}

      <Field
        id={`${idPrefix}-name`}
        label="Name"
        value={values.name}
        error={nameError}
        maxLength={200}
        placeholder={values.provider === "slack" ? "Team Slack" : "Weather API"}
        onChange={(event) => set("name", event.target.value)}
      />

      {values.provider === "http" ? (
        <>
          <TextareaField
            id={`${idPrefix}-hosts`}
            label="Allowed hosts"
            hint="One host name per line, like api.example.com. Agents can only call these hosts."
            value={values.hosts}
            spellCheck={false}
            onChange={(event) => set("hosts", event.target.value)}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id={`${idPrefix}-auth-header`}
              label="Header that carries the secret"
              value={values.authHeader}
              spellCheck={false}
              onChange={(event) => set("authHeader", event.target.value)}
            />
            <Field
              id={`${idPrefix}-auth-scheme`}
              label="Prefix before the secret"
              hint="Usually Bearer. Leave empty to send the secret alone."
              value={values.authScheme}
              spellCheck={false}
              onChange={(event) => set("authScheme", event.target.value)}
            />
          </div>
        </>
      ) : (
        <TextareaField
          id={`${idPrefix}-channels`}
          label="Allowed channels"
          hint="One Slack channel id per line, like C0123456789. Messages to other channels are refused."
          value={values.channels}
          spellCheck={false}
          onChange={(event) => set("channels", event.target.value)}
        />
      )}

      {mode === "create" && (
        <Field
          id={`${idPrefix}-secret`}
          type="password"
          autoComplete="new-password"
          label="Secret (optional)"
          hint={
            values.provider === "slack"
              ? "The bot token. It is stored encrypted and can never be shown again."
              : "An API key or token, if the service needs one. It is stored encrypted and can never be shown again."
          }
          value={values.secret}
          onChange={(event) => set("secret", event.target.value)}
        />
      )}

      <ErrorNotice error={error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : mode === "create" ? "Add integration" : "Save settings"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
