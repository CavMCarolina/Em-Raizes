// Notificações push (Web Push) do navegador para o celular do administrador.
import { api } from "../api/cliente";

export type SituacaoPush =
  | "sem_suporte" // navegador sem service worker/push
  | "precisa_instalar" // iPhone: só funciona com o app adicionado à tela inicial
  | "sem_service_worker" // modo desenvolvimento (Vite): o service worker só existe no app compilado
  | "bloqueado" // a pessoa negou a permissão
  | "desativado" // pode ativar
  | "ativado";

function ehIphone(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

function instaladoNaTela(): boolean {
  return window.matchMedia?.("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
}

export function suportaPush(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

/** Converte a chave pública VAPID (base64url) para o formato do navegador. */
export function chaveParaBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const preenchido = (base64url + "===".slice((base64url.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const binario = atob(preenchido);
  const bytes = new Uint8Array(new ArrayBuffer(binario.length));
  for (let i = 0; i < binario.length; i++) bytes[i] = binario.charCodeAt(i);
  return bytes;
}

async function registro(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null;
  return (await navigator.serviceWorker.getRegistration()) ?? null;
}

export async function situacaoPush(): Promise<SituacaoPush> {
  if (!suportaPush()) return ehIphone() && !instaladoNaTela() ? "precisa_instalar" : "sem_suporte";
  if (ehIphone() && !instaladoNaTela()) return "precisa_instalar";
  if (Notification.permission === "denied") return "bloqueado";
  const reg = await registro();
  if (!reg) return "sem_service_worker";
  const inscricao = await reg.pushManager.getSubscription();
  return inscricao && Notification.permission === "granted" ? "ativado" : "desativado";
}

/** Pede permissão, inscreve este aparelho e manda a inscrição para o servidor. */
export async function ativarPush(chavePublica: string): Promise<SituacaoPush> {
  const permissao = await Notification.requestPermission();
  if (permissao !== "granted") return permissao === "denied" ? "bloqueado" : "desativado";
  const reg = await registro();
  if (!reg) return "sem_service_worker";
  let inscricao = await reg.pushManager.getSubscription();
  if (inscricao) {
    // se o servidor trocou de chave, a inscrição antiga não serve mais
    const atual = inscricao.options.applicationServerKey;
    const nova = chaveParaBytes(chavePublica);
    const igual = atual && new Uint8Array(atual).every((b, i) => b === nova[i]);
    if (!igual) {
      await inscricao.unsubscribe();
      inscricao = null;
    }
  }
  try {
    inscricao ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: chaveParaBytes(chavePublica) });
  } catch (e) {
    // comum em navegadores embutidos, modo anônimo ou sem o serviço de push do fabricante
    throw new Error(
      `O navegador recusou a inscrição (${(e as Error).name}). Use o Chrome ou o Edge no celular, ou o app instalado na tela inicial.`,
    );
  }
  await api.notificacoes.inscrever(inscricao.toJSON());
  return "ativado";
}

export async function desativarPush(): Promise<SituacaoPush> {
  const reg = await registro();
  const inscricao = await reg?.pushManager.getSubscription();
  if (inscricao) {
    await api.notificacoes.cancelar(inscricao.endpoint).catch(() => undefined);
    await inscricao.unsubscribe();
  }
  return "desativado";
}

/** Ao abrir o app: reenvia a inscrição (o servidor guarda em memória e pode ter reiniciado). */
export async function sincronizarPush(): Promise<void> {
  if (!suportaPush() || Notification.permission !== "granted") return;
  const reg = await registro();
  const inscricao = await reg?.pushManager.getSubscription();
  if (inscricao) await api.notificacoes.inscrever(inscricao.toJSON()).catch(() => undefined);
}

export const TEXTO_SITUACAO: Record<SituacaoPush, string> = {
  sem_suporte: "Este navegador não recebe notificações push.",
  precisa_instalar: "No iPhone, adicione o app à tela inicial (Compartilhar → Adicionar à Tela de Início) e abra por lá.",
  sem_service_worker: "Disponível no app compilado (npm run build) ou instalado no celular.",
  bloqueado: "Notificações bloqueadas. Libere nas configurações do navegador para este site.",
  desativado: "Receba no celular os avisos de alerta, chuva forte, parada de emergência e fotos com risco.",
  ativado: "Este aparelho vai receber os avisos, mesmo com o app fechado.",
};
