import { MessageCircle, Send } from "lucide-react";
import { type FormEvent } from "react";

type Lang = "en" | "zh";

type ResearchText = {
  researchChatEmpty: string;
  directView: string;
  keyPoints: string;
  risks: string;
  whatToCheckNext: string;
  evidenceUsed: string;
  followUps: string;
};

type ResearchAnswer = {
  direct_view: string;
  key_points: string[];
  risk_flags: string[];
  what_to_check_next: string[];
  evidence_used: string[];
  follow_up_questions: string[];
  safety_note: string;
};

type ResearchPayload = {
  status?: string;
  fallback_model_used?: boolean;
  answer?: ResearchAnswer;
};

type ResearchMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  payload?: ResearchPayload;
};

type SelectedStock = { symbol: string; level: string; score: number };
type AiStatus = { status: string };
type AiDecision = { ai_decision?: { action?: string } };

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="fact"><span>{label}</span><strong>{value}</strong></div>;
}

function Narrative({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="narrative">
      <strong>{title}</strong>
      {items.slice(0, 5).map((item) => <p key={item}>{item}</p>)}
    </div>
  );
}

function ResearchChatAnswerCard({ payload, text }: { payload: ResearchPayload; text: ResearchText }) {
  const answer = payload.answer;
  if (!answer) return null;
  const isDegraded = payload.status !== "available" || Boolean(payload.fallback_model_used);
  return (
    <div className={`deep-chat-answer-card ${isDegraded ? "degraded" : ""}`}>
      {isDegraded ? <p className="secondary-note">研究上下文暂不可用，结论仅供人工复核。</p> : null}
      <Fact label={text.directView} value={answer.direct_view} />
      <Narrative title={text.keyPoints} items={answer.key_points} />
      <Narrative title={text.risks} items={answer.risk_flags} />
      <Narrative title={text.whatToCheckNext} items={answer.what_to_check_next} />
      {answer.evidence_used?.length ? <Narrative title={text.evidenceUsed} items={answer.evidence_used} /> : null}
      <Narrative title={text.followUps} items={answer.follow_up_questions} />
      <p className="secondary-note">{answer.safety_note}</p>
    </div>
  );
}

export function DeepResearchChatPanel({
  text,
  lang,
  selected,
  aiStatus,
  aiDecision,
  conclusion,
  dataStatus,
  state,
  messages,
  input,
  onInputChange,
  onSend,
  onAsk,
}: {
  text: ResearchText;
  lang: Lang;
  selected: SelectedStock;
  aiStatus: AiStatus | null;
  aiDecision: AiDecision | null;
  conclusion: string;
  dataStatus: string;
  state: "idle" | "loading" | "ready" | "error";
  messages: ResearchMessage[];
  input: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onAsk: (question: string) => void;
}) {
  const promptIdeas = lang === "zh"
    ? [
        `分析 ${selected.symbol} 的风险收益与更合适的入场区。`,
        `什么条件会改变对 ${selected.symbol} 的结论？`,
        `对比 ${selected.symbol} 的看多与看空依据。`,
      ]
    : [
        `Analyze ${selected.symbol}'s risk/reward and better entry zone.`,
        `What would change the conclusion on ${selected.symbol}?`,
        `Compare bullish and bearish evidence for ${selected.symbol}.`,
      ];
  const available = aiStatus?.status === "available";
  return (
    <section className="panel deep-research-chat" id="deep-research-chat-workspace">
      <div className="deep-chat-head">
        <div>
          <span className="eyebrow">{lang === "zh" ? "股票研究" : "Stock research"}</span>
          <h2>{lang === "zh" ? "深度研究" : "Deep Research"}</h2>
          <p>{lang === "zh" ? "围绕当前股票的结构、风险、入场条件和图表证据展开复核。" : "Review the selected stock's structure, risks, entry conditions, and chart evidence."}</p>
        </div>
      </div>
      <div className="deep-chat-context">
        <Fact label={lang === "zh" ? "股票" : "Symbol"} value={selected.symbol} />
        <Fact label={lang === "zh" ? "评分" : "Score"} value={`${selected.level} / ${selected.score.toFixed(2)}`} />
        <Fact label={lang === "zh" ? "研究结论" : "Conclusion"} value={conclusion || aiDecision?.ai_decision?.action || "-"} />
        <Fact label={lang === "zh" ? "数据状态" : "Data status"} value={dataStatus || "-"} />
      </div>
      <div className="deep-chat-messages">
        {messages.length === 0 ? (
          <div className="deep-chat-empty">
            <MessageCircle size={28} />
            <strong>{text.researchChatEmpty}</strong>
            <div className="deep-chat-prompts">
              {promptIdeas.map((prompt) => <button type="button" key={prompt} onClick={() => onAsk(prompt)} disabled={state === "loading" || !available}>{prompt}</button>)}
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <article className={`deep-chat-message ${message.role}`} key={message.id}>
              <div className="deep-chat-bubble">
                <strong>{message.role === "user" ? (lang === "zh" ? "你" : "You") : "KQUANT"}</strong>
                <p>{message.content}</p>
              </div>
              {message.payload?.answer ? <ResearchChatAnswerCard payload={message.payload} text={text} /> : null}
            </article>
          ))
        )}
        {state === "loading" ? <div className="deep-chat-message assistant"><div className="deep-chat-bubble"><strong>KQUANT</strong><p>{lang === "zh" ? "正在整理研究…" : "Preparing research…"}</p></div></div> : null}
      </div>
      <form className="deep-chat-input" onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); onSend(); }}>
        <textarea value={input} onChange={(event) => onInputChange(event.target.value)} placeholder={available ? (lang === "zh" ? "询问形态、风险、入场条件或需要继续确认的证据…" : "Ask about structure, risk, entry conditions, or evidence to confirm…") : (lang === "zh" ? "研究服务暂时不可用" : "Research service is temporarily unavailable")} disabled={state === "loading" || !available} />
        <button type="submit" disabled={state === "loading" || !available || !input.trim()}><Send size={15} />{state === "loading" ? (lang === "zh" ? "整理中" : "Working") : (lang === "zh" ? "提问" : "Ask")}</button>
      </form>
      {!available ? <p className="secondary-note">{lang === "zh" ? "研究服务暂时不可用，请稍后再试。" : "Research service is temporarily unavailable. Please try again later."}</p> : null}
    </section>
  );
}
