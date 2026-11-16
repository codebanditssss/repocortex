export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Embedded browsers can block the Clipboard API while allowing a copy command.
    const active = document.activeElement;
    const field = document.createElement("textarea");
    field.value = text;
    field.readOnly = true;
    field.style.cssText = "position:fixed;top:0;left:0;opacity:0;font-size:16px;pointer-events:none";
    document.body.appendChild(field);
    try {
      field.focus({ preventScroll: true });
      field.select();
      field.setSelectionRange(0, text.length);
      return document.execCommand("copy");
    } catch {
      return false;
    } finally {
      field.remove();
      if (active instanceof HTMLElement) active.focus({ preventScroll: true });
    }
  }
}
