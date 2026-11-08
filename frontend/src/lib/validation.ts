const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export const MIN_PASSWORD_LENGTH = 8;

export function validateEmail(value: string): string | null {
  const email = value.trim();
  if (!email) return "Enter your email address.";
  if (email.length > 320 || !EMAIL_PATTERN.test(email)) return "Enter a valid email address.";
  return null;
}

export function validateNewPassword(value: string): string | null {
  if (!value) return "Choose a password.";
  if (value.length < MIN_PASSWORD_LENGTH) {
    return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  return null;
}

export function validatePasswordConfirmation(
  password: string,
  confirmation: string,
): string | null {
  if (!confirmation) return "Repeat the password.";
  return password === confirmation ? null : "The passwords do not match.";
}

export function validateOrganizationName(value: string): string | null {
  const name = value.trim();
  if (name.length < 2) return "Use at least 2 characters.";
  if (name.length > 100) return "Use at most 100 characters.";
  return null;
}

const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{1,62}$/;

/** Empty is allowed: the API then derives a URL name from the organization name. */
export function validateSlug(value: string): string | null {
  const slug = value.trim();
  if (!slug) return null;
  return SLUG_PATTERN.test(slug)
    ? null
    : "Use 2-63 lowercase letters, numbers and hyphens, starting with a letter or number.";
}
