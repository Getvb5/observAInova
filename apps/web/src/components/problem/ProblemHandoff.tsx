export function ProblemHandoff() {
  return (
    <section className="panel handoff-panel" aria-labelledby="handoff-title">
      <div className="confirmation-mark" aria-hidden="true">
        ✓
      </div>
      <p className="eyebrow">Formulação registrada</p>
      <h1 id="handoff-title">Problema confirmado</h1>
      <p className="handoff-copy">
        O mapa será construído somente com contribuições científicas validadas. Nenhuma
        sugestão automática será apresentada como evidência.
      </p>
      <div className="next-stage" aria-label="Próxima etapa">
        <span className="next-stage__number">02</span>
        <div>
          <strong>Mapeamento científico em preparação</strong>
          <p>
            Teses e dissertações serão relacionadas ao problema por evidências,
            contexto de aplicação, barreiras e condições de uso.
          </p>
        </div>
      </div>
    </section>
  );
}
