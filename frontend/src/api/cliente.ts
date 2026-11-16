import type {
  ChuvaDia,
  Comando,
  DetalheCelula,
  Estado,
  Evento,
  Info,
  Mapa,
  MensagemChat,
  MissaoRobo,
  RespostaFoto,
  RespostaIA,
  RespostaPlano,
  StatusNotificacoes,
} from "./tipos";

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
const CHAVE_TOKEN = "em-raizes.token";

export class ErroApi extends Error {
  constructor(
    public status: number,
    public codigo: string,
    mensagem: string,
  ) {
    super(mensagem);
  }
}

export const sessao = {
  obter(): string | null {
    try {
      return localStorage.getItem(CHAVE_TOKEN);
    } catch {
      return null;
    }
  },
  salvar(token: string) {
    try {
      localStorage.setItem(CHAVE_TOKEN, token);
    } catch {
      /* navegação privada: o login vale só enquanto a aba estiver aberta */
    }
  },
  limpar() {
    try {
      localStorage.removeItem(CHAVE_TOKEN);
    } catch {
      /* nada a fazer */
    }
  },
};

let aoExpirar: (() => void) | null = null;
export function quandoSessaoExpirar(fn: () => void) {
  aoExpirar = fn;
}

export function novaChaveIdempotencia(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return `app-${crypto.randomUUID()}`;
  return `app-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

interface Opcoes extends RequestInit {
  json?: unknown;
  aceitar409?: boolean;
}

async function requisitar<T>(caminho: string, opcoes: Opcoes = {}): Promise<T> {
  const { json, aceitar409, ...init } = opcoes;
  const headers = new Headers(init.headers);
  const token = sessao.obter();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (json !== undefined) headers.set("Content-Type", "application/json");
  let resposta: Response;
  try {
    resposta = await fetch(BASE + caminho, { ...init, headers, body: json !== undefined ? JSON.stringify(json) : init.body });
  } catch {
    throw new ErroApi(0, "sem_conexao", "Sem conexão com o servidor.");
  }
  if (resposta.status === 401 && token) {
    sessao.limpar();
    aoExpirar?.();
  }
  const ehJson = (resposta.headers.get("content-type") ?? "").includes("json");
  const dados = ehJson ? await resposta.json() : null;
  if (resposta.ok || (aceitar409 && resposta.status === 409)) return dados as T;
  const detalhe = dados?.detail;
  const codigo = typeof detalhe === "object" && detalhe?.codigo ? detalhe.codigo : `http_${resposta.status}`;
  const mensagem =
    typeof detalhe === "object" && detalhe?.mensagem
      ? detalhe.mensagem
      : typeof detalhe === "string"
        ? detalhe
        : `Erro ${resposta.status}`;
  throw new ErroApi(resposta.status, codigo, mensagem);
}

/** Comandos sempre devolvem um Comando (status "recusado" quando a regra de segurança barra). */
function comando(caminho: string, corpo: unknown = {}): Promise<Comando> {
  return requisitar<Comando>(caminho, {
    method: "POST",
    json: corpo,
    aceitar409: true,
    headers: { "Idempotency-Key": novaChaveIdempotencia() },
  });
}

export const api = {
  info: () => requisitar<Info>("/api/info"),
  login: (usuario: string, senha: string) =>
    requisitar<{ token: string; expira_em: string; usuario: string }>("/api/auth/login", {
      method: "POST",
      json: { usuario, senha },
    }),
  estado: () => requisitar<Estado>("/api/estado"),
  mapa: () => requisitar<Mapa>("/api/mapa"),
  celula: (id: string) => requisitar<DetalheCelula>(`/api/mapa/celulas/${encodeURIComponent(id)}`),
  chuva: () => requisitar<ChuvaDia[]>("/api/chuva"),
  comandos: (limite = 50) => requisitar<Comando[]>(`/api/comandos?limite=${limite}`),
  eventos: (desde = 0) => requisitar<Evento[]>(`/api/eventos?desde=${desde}`),
  async imagemAerea(): Promise<string> {
    const token = sessao.obter();
    const r = await fetch(`${BASE}/api/mapa/imagem.png`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!r.ok) throw new ErroApi(r.status, `http_${r.status}`, "Não foi possível carregar a foto do drone.");
    return URL.createObjectURL(await r.blob());
  },

  enviarDrone: () => comando("/api/comandos/drone/voo"),
  robo: (missao: MissaoRobo, celulas?: string[]) =>
    comando(`/api/comandos/robo/${missao}`, celulas?.length ? { celulas } : {}),
  recolherRobo: () => comando("/api/comandos/robo/recolher"),
  emergencia: () => comando("/api/comandos/emergencia"),
  liberarFrota: () => comando("/api/comandos/liberar"),
  mudarClima: (cenario: string) => comando("/api/simulacao/clima", { cenario }),

  chat: (pergunta: string, historico: MensagemChat[]) =>
    requisitar<RespostaIA>("/api/ia/chat", {
      method: "POST",
      json: { pergunta, historico: historico.map(({ role, content }) => ({ role, content })) },
    }),
  explicar: (celula: string) => requisitar<RespostaIA>(`/api/ia/explicar/${encodeURIComponent(celula)}`, { method: "POST" }),
  sms: () => requisitar<RespostaIA>("/api/ia/sms", { method: "POST" }),
  plano: () => requisitar<RespostaPlano>("/api/ia/plano", { method: "POST" }),
  foto: (imagem: string, observacao: string, celula?: string) =>
    requisitar<RespostaFoto>("/api/ia/foto", { method: "POST", json: { imagem, observacao, celula: celula || null } }),

  notificacoes: {
    status: () => requisitar<StatusNotificacoes>("/api/notificacoes"),
    inscrever: (inscricao: PushSubscriptionJSON) =>
      requisitar<{ inscrito: boolean; inscricoes: number }>("/api/notificacoes/inscrever", { method: "POST", json: inscricao }),
    cancelar: (endpoint: string) =>
      requisitar<{ inscrito: boolean }>("/api/notificacoes/cancelar", { method: "POST", json: { endpoint } }),
    teste: () => requisitar<{ enviadas: number; falhas: number }>("/api/notificacoes/teste", { method: "POST" }),
  },
};
