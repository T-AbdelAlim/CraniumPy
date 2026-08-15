// which shipped template to compare against by default, given the current
// target/alt-frontal/CoM settings - ported from frontend_legacy/app.js's
// defaultTemplateForCurrentResult(). clipped_template_xy is built in the
// sellion frame; the subnasal variants are built in the alt-frontal frame -
// picking the wrong one for the current registration mode leaves the
// overlay visibly offset even when the actual registration is fine.
export function defaultTemplateForTarget(target, useAltFrontal, comTranslation) {
  if (target !== "cranium") return "template_face";
  if (useAltFrontal) return comTranslation ? "template_xy_subanasal_com" : "template_xy_subanasal";
  return comTranslation ? "clipped_template_xy_com" : "clipped_template_xy";
}

export function templateChoiceStorageKey(target) {
  return `craniumpy.templateChoice.${target}`;
}

export function customTemplatePathStorageKey(target) {
  return `craniumpy.customTemplatePath.${target}`;
}
