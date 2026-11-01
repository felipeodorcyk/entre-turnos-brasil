/**
 * Feature flags do P0. Módulos P1/P2 permanecem desligados nesta entrega:
 * não há rota, botão ou número simulando análise concluída.
 */
export const FEATURES = {
  secoes: false,
  locais_votacao: false,
  entorno_1km: false,
  horarios: false,
  modelos_ajustados: false,
  origens_estimadas: false,
  comparar_recortes: false,
  alegacoes_editoriais: false,
} as const;

export const FEATURE_LABELS: Record<keyof typeof FEATURES, string> = {
  secoes: "Consulta por seção eleitoral",
  locais_votacao: "Locais de votação e agrupamento",
  entorno_1km: "Contexto de entorno de 1 km",
  horarios: "Horários de encerramento e totalização",
  modelos_ajustados: "Modelos ajustados e associações",
  origens_estimadas: "Origens estimadas de votos",
  comparar_recortes: "Comparação A/B de recortes",
  alegacoes_editoriais: "Módulo editorial de alegações",
};
