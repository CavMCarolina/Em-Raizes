// Tipos das respostas da API (espelham backend/src/em_raizes/operacoes/modelos.py e api/main.py).

export type NivelAlerta = "normal" | "atencao" | "alerta" | "alerta_maximo";
export type ClasseRisco = "baixo" | "moderado" | "alto" | "critico";
export type TipoComando =
  | "voo_drone"
  | "plantio"
  | "irrigacao"
  | "inspecao"
  | "recolher_robo"
  | "parada_emergencia"
  | "liberar_frota"
  | "mudar_clima";
export type StatusComando = "em_execucao" | "concluido" | "recusado" | "cancelado";
export type Origem = "admin" | "sistema";
export type MissaoRobo = "plantio" | "irrigacao" | "inspecao";

export interface Posicao {
  linha: number;
  coluna: number;
}

export interface Dispositivo {
  id: string;
  tipo: "drone" | "robo";
  nome: string;
  status: "na_base" | "em_missao" | "parado";
  bateria: number;
  comando_atual: string | null;
  posicao: Posicao | null;
}

export interface Comando {
  id: string;
  tipo: TipoComando;
  dispositivo: string | null;
  origem: Origem;
  status: StatusComando;
  progresso: number;
  celulas: string[];
  ignoradas: Record<string, string>;
  parametros: Record<string, unknown>;
  resultado: Record<string, unknown>;
  codigo_recusa: string | null;
  motivo: string | null;
  criado_em: string;
  iniciado_em: string | null;
  concluido_em: string | null;
  duracao_s: number;
  chave_idempotencia: string | null;
}

export interface Evento {
  id: number;
  quando: string;
  tipo: string;
  nivel: "info" | "aviso" | "perigo";
  mensagem: string;
  origem: Origem;
  comando_id: string | null;
}

export interface Recomendacao {
  id: string;
  acao: TipoComando;
  prioridade: "alta" | "media" | "baixa";
  titulo: string;
  motivo: string;
  celulas: string[];
}

export interface Alerta {
  nivel: NivelAlerta;
  titulo: string;
  cor: string;
  mensagem: string;
  acao: string;
  casas_em_risco: number;
  pessoas_em_risco: number;
  celulas_evacuar: string[];
}

export interface Clima {
  cenario: string;
  nome: string;
  chuva_72h: number;
  previsao_24h: number;
  descricao: string;
  real: boolean;
  faixa: "seco" | "moderada" | "forte" | "extrema";
  atualizado_em: string | null;
  erro: string | null;
}

export interface UltimoVoo {
  voo_id: string;
  data: string;
  cenario: string;
  nivel_alerta: NivelAlerta;
  risco_medio: number;
  celulas_alto_ou_critico: number;
  fissuras: number;
  pessoas_em_risco: number;
  nome_cenario: string;
  chuva_72h: number;
  previsao_24h: number;
}

export interface Estatisticas {
  celulas: number;
  area_ha: number;
  casas: number;
  moradores: number;
  por_classe: Record<ClasseRisco, number>;
  por_classe_24h: Record<ClasseRisco, number>;
  risco_medio: number;
  risco_medio_24h: number;
  fissuras: number;
  vazamentos: number;
  celulas_plantio: number;
  celulas_plantio_manual: number;
  mudas: number;
  celulas_irrigar: number;
  litros: number;
  cobertura_media: number;
  umidade_media: number;
}

export interface Estado {
  horario: string;
  dispositivos: Dispositivo[];
  comandos_ativos: Comando[];
  ultimos_comandos: Comando[];
  alerta: Alerta;
  robo_liberado: boolean;
  frota_parada: boolean;
  ultimo_voo: UltimoVoo;
  clima_atual: Clima;
  estatisticas: Estatisticas;
  contadores: { mudas_plantadas: number; litros_aplicados: number; fissuras_inspecionadas: number; voos: number };
  recomendacoes: Recomendacao[];
  ultimo_evento_id: number;
}

export interface Celula {
  celula: string;
  linha: number;
  coluna: number;
  setor: string;
  risco: number;
  classe_risco: ClasseRisco;
  risco_24h: number;
  classe_risco_24h: ClasseRisco;
  tendencia: "subindo" | "caindo" | "estavel";
  umidade_pct: number;
  umidade_24h: number;
  cobertura_vegetal: number;
  declividade_graus: number;
  elevacao_m: number;
  tipo_solo: string;
  solo_visao: string;
  confianca_visao: number;
  casas: number;
  moradores_estimados: number;
  fissura_detectada: boolean;
  prob_fissura: number;
  vazamento: boolean;
  plantio_recomendado: boolean;
  plantio_manual: boolean;
  precisa_irrigar: boolean;
  mudas: number;
  litros_irrigacao: number;
}

export interface Mapa {
  voo_id: string;
  data_voo: string;
  linhas: number;
  colunas: number;
  tamanho_celula_m: number;
  celulas: Celula[];
}

export interface DetalheCelula {
  celula: Celula;
  explicacao: { celula: string; fatores_0a1: Record<string, number>; contribuicao_pts: Record<string, number> };
}

export interface Info {
  nome_app: string;
  versao: string;
  ambiente: string;
  login_habilitado: boolean;
  ia_online: boolean;
  modelo_ia: string;
  dados_simulados: boolean;
  cenarios: Record<string, string>;
  push_habilitado: boolean;
  analise_foto: boolean;
}

export interface SinalFoto {
  tipo: string;
  descricao: string;
  gravidade: "baixa" | "media" | "alta";
}

export interface AnaliseFoto {
  e_encosta: boolean;
  risco: "baixo" | "moderado" | "alto" | "critico" | "indeterminado";
  confianca: "baixa" | "media" | "alta";
  resumo: string;
  sinais: SinalFoto[];
  recomendacoes: string[];
}

export interface RespostaFoto {
  analise: AnaliseFoto;
  modelo: string;
  tokens: number;
  latencia_s: number;
}

export interface StatusNotificacoes {
  habilitado: boolean;
  chave_publica: string | null;
  inscricoes: number;
  enviadas: number;
  falhas: number;
  ultimo_erro: string | null;
}

export interface RespostaIA {
  texto: string;
  modo: "ia" | "offline";
  modelo: string | null;
  fontes: string[];
  aviso: string | null;
  tokens: number;
  latencia_s: number;
}

export interface AcaoPlano {
  prioridade: number;
  tipo: string;
  local: string;
  descricao: string;
  responsavel: string;
}

export interface RespostaPlano extends RespostaIA {
  plano: { nivel_alerta: NivelAlerta; resumo: string; acoes: AcaoPlano[] };
}

export interface ChuvaDia {
  data: string;
  chuva_mm: number;
  tipo: "observada" | "prevista";
}

export interface MensagemChat {
  role: "user" | "assistant";
  content: string;
  meta?: string;
}
