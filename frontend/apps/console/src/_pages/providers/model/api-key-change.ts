export function providerApiKeyChange({
  isEditing,
  draft,
  removeConfirmed,
}: {
  isEditing: boolean;
  draft: string;
  removeConfirmed: boolean;
}): string | null {
  if (!isEditing) return draft;
  if (removeConfirmed) return "";
  return draft || null;
}
