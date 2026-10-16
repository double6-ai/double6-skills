/* 儿童闯关页是展示适配器。组合合同只声明模块、注意力区和成熟度，不在此复制专用 UI。 */
function childPlaygroundCompositionReady() {
  return Boolean(window.COMPOSITION_PACK || typeof COMPOSITION_PACK !== "undefined");
}
