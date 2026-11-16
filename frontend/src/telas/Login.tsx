import { TriangleAlert } from "lucide-react";
import { useState } from "react";
import { api, ErroApi, sessao } from "../api/cliente";
import type { Info } from "../api/tipos";
import { NOME_APP } from "../config";

export function Login({ info, aoEntrar }: { info: Info | null; aoEntrar: (usuario: string) => void }) {
  const [usuario, setUsuario] = useState("admin");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  return (
    <main className="login" data-testid="tela-login">
      <form
        className="login__caixa"
        onSubmit={async (e) => {
          e.preventDefault();
          setEnviando(true);
          setErro(null);
          try {
            const r = await api.login(usuario, senha);
            sessao.salvar(r.token);
            aoEntrar(r.usuario);
          } catch (err) {
            setErro((err as ErroApi).message);
          } finally {
            setEnviando(false);
          }
        }}
      >
        <img src="/icone.svg" alt="" width={72} height={72} />
        <h1>{info?.nome_app ?? NOME_APP}</h1>
        <p className="mudo">Administração do drone e do robô jardineiro</p>
        {info && !info.login_habilitado && (
          <p className="faixa faixa--aviso" data-testid="login-desativado">
            Login desativado: defina <code>EM_RAIZES_ADMIN_SENHA</code> no servidor.
          </p>
        )}
        <label>
          Usuário
          <input id="login-usuario" data-testid="login-usuario" value={usuario} onChange={(e) => setUsuario(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          Senha
          <input
            id="login-senha"
            data-testid="login-senha"
            type="password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {erro && (
          <p className="faixa faixa--erro" role="alert" data-testid="login-erro">
            {erro}
          </p>
        )}
        <button type="submit" id="btn-entrar" data-testid="btn-entrar" className="botao botao--primario botao--grande" disabled={enviando}>
          {enviando ? "Entrando…" : "Entrar"}
        </button>
        <p className="mudo pequeno com-icone com-icone--centro">
          <TriangleAlert size={15} aria-hidden className="ico ico--aviso" /> MVP acadêmico: drone e robô simulados. Em emergência ligue 199.
        </p>
      </form>
    </main>
  );
}
