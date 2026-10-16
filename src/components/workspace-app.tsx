"use client";

import {
  Activity,
  ArrowDownToLine,
  ArrowLeftRight,
  ArrowUp,
  BarChart3,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Command,
  Copy,
  Gauge,
  KeyRound,
  LogOut,
  MessageSquare,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings2,
  Sparkles,
  StopCircle,
  ThumbsDown,
  ThumbsUp,
  Workflow,
  Zap,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  FormEvent,
  KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  api,
  clearToken,
  consumeSse,
  Conversation,
  getToken,
  Message,
  Model,
  setToken,
  StreamEvent,
  Usage,
  User,
  Workspace,
} from "@/lib/api";

type View = "chat" | "compare" | "usage";
type AuthMode = "login" | "register";
const EMPTY_CONVERSATIONS: Conversation[] = [];
const EMPTY_MESSAGES: Message[] = [];
const EMPTY_MODELS: Model[] = [];
const starterPrompts = [
  "Help me plan a focused week",
  "Explain a tricky concept simply",
  "Review this idea and find the gaps",
];

function formatCurrency(amount: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: amount > 0 && amount < 0.01 ? 4 : 2,
  }).format(amount);
}

function formatCount(value: number) {
  return new Intl.NumberFormat("en-US", { notation: value > 99_999 ? "compact" : "standard" }).format(value);
}

function initialMessage(id: string, role: Message["role"], content: string): Message {
  return {
    id,
    role,
    content,
    model_id: null,
    input_tokens: 0,
    output_tokens: 0,
    latency_ms: null,
    estimated_cost_usd: 0,
    status: "complete",
    created_at: new Date().toISOString(),
  };
}

export function WorkspaceApp() {
  const queryClient = useQueryClient();
  const [token, setTokenState] = useState("");
  const [tokenReady, setTokenReady] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authForm, setAuthForm] = useState({
    display_name: "",
    email: "",
    password: "",
    workspace_name: "",
  });
  const [view, setView] = useState<View>("chat");
  const [selectedConversationId, setSelectedConversationId] = useState("");
  const [selectedModelId, setSelectedModelId] = useState("");
  const [compareModelIds, setCompareModelIds] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [conversationSearch, setConversationSearch] = useState("");
  const [autoRoute, setAutoRoute] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamError, setStreamError] = useState("");
  const [toast, setToast] = useState("");
  const [budgetDraft, setBudgetDraft] = useState("");
  const [modelPermissionDraft, setModelPermissionDraft] = useState<string[]>();
  const [budgetSaved, setBudgetSaved] = useState(false);
  const abortController = useRef<AbortController | null>(null);
  const messagesEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setTokenState(getToken());
      setTokenReady(true);
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const userQuery = useQuery({
    queryKey: ["user", token],
    queryFn: () => api<User>("/auth/me"),
    enabled: Boolean(token),
  });
  const workspaceQuery = useQuery({
    queryKey: ["workspace", token],
    queryFn: () => api<Workspace>("/auth/workspace"),
    enabled: Boolean(token),
  });
  const modelsQuery = useQuery({
    queryKey: ["models", token],
    queryFn: () => api<Model[]>("/models"),
    enabled: Boolean(token),
  });
  const conversationsQuery = useQuery({
    queryKey: ["conversations", token],
    queryFn: () => api<Conversation[]>("/conversations"),
    enabled: Boolean(token),
  });
  const usageQuery = useQuery({
    queryKey: ["usage", token],
    queryFn: () => api<Usage>("/usage/summary"),
    enabled: Boolean(token) && view === "usage",
  });
  const conversations = conversationsQuery.data ?? EMPTY_CONVERSATIONS;
  const models = modelsQuery.data ?? EMPTY_MODELS;
  const user = userQuery.data;
  const workspace = workspaceQuery.data;
  const activeConversationId =
    selectedConversationId || conversations[0]?.id || "";
  const activeConversation = conversations.find(
    (conversation) => conversation.id === activeConversationId,
  );
  const selectedModel = models.find((model) => model.id === selectedModelId) ??
    models.find((model) => model.id === workspace?.default_model_id) ??
    models.find((model) => model.available && model.enabled) ??
    models[0];
  const effectiveCompareModelIds = compareModelIds.length
    ? compareModelIds
    : models.slice(0, 2).map((model) => model.id);
  const messagesQuery = useQuery({
    queryKey: ["messages", token, activeConversationId],
    queryFn: () => api<Message[]>(`/conversations/${activeConversationId}/messages`),
    enabled: Boolean(token && activeConversationId),
  });
  const messages = messagesQuery.data ?? EMPTY_MESSAGES;
  const filteredConversations = useMemo(
    () =>
      conversations.filter((conversation) =>
        conversation.title.toLowerCase().includes(conversationSearch.toLowerCase()),
      ),
    [conversations, conversationSearch],
  );
  const compareResponses = useMemo(() => {
    let latestPromptIndex = -1;
    messages.forEach((message, index) => {
      if (message.role === "user") latestPromptIndex = index;
    });
    return messages
      .slice(latestPromptIndex + 1)
      .filter((message) => message.role === "assistant");
  }, [messages]);
  const availableModels = models.filter((model) => model.available && model.enabled);
  const allowedModelIds = modelPermissionDraft ??
    workspace?.allowed_model_ids ??
    models.filter((model) => model.enabled).map((model) => model.id);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streaming]);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(""), 2200);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const refreshConversationData = async (conversationId: string) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["messages", token, conversationId] }),
      queryClient.invalidateQueries({ queryKey: ["conversations", token] }),
      queryClient.invalidateQueries({ queryKey: ["usage", token] }),
    ]);
  };

  const createConversation = async (mode: "chat" | "compare" = "chat") => {
    const conversation = await api<Conversation>("/conversations", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
    setSelectedConversationId(conversation.id);
    queryClient.setQueryData<Conversation[]>(["conversations", token], (existing = []) => [
      conversation,
      ...existing,
    ]);
    queryClient.setQueryData<Message[]>(["messages", token, conversation.id], []);
    return conversation;
  };

  const beginAuth = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAuthError("");
    setAuthBusy(true);
    try {
      const result = await api<{ access_token: string; user: User }>("/auth/" + authMode, {
        method: "POST",
        body: JSON.stringify(
          authMode === "register"
            ? authForm
            : { email: authForm.email, password: authForm.password },
        ),
      });
      setToken(result.access_token);
      setTokenState(result.access_token);
      queryClient.setQueryData(["user", result.access_token], result.user);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Unable to sign in.");
    } finally {
      setAuthBusy(false);
    }
  };

  const signOut = () => {
    abortController.current?.abort();
    clearToken();
    setTokenState("");
    setSelectedConversationId("");
    queryClient.clear();
  };

  const updateMessage = (conversationId: string, messageId: string, update: (message: Message) => Message) => {
    queryClient.setQueryData<Message[]>(["messages", token, conversationId], (existing = []) =>
      existing.map((message) => (message.id === messageId ? update(message) : message)),
    );
  };

  const streamRequest = async (
    conversationId: string,
    userText: string,
    mode: "chat" | "compare",
  ) => {
    const controller = new AbortController();
    abortController.current = controller;
    setStreaming(true);
    setStreamError("");
    const temporaryUser = initialMessage(crypto.randomUUID(), "user", userText);
    queryClient.setQueryData<Message[]>(
      ["messages", token, conversationId],
      (existing = []) => [...existing, temporaryUser],
    );
    try {
      const path =
        mode === "compare"
          ? `/conversations/${conversationId}/compare`
          : `/conversations/${conversationId}/messages`;
      const payload =
        mode === "compare"
          ? { content: userText, model_id: effectiveCompareModelIds[0], model_ids: effectiveCompareModelIds }
          : { content: userText, model_id: selectedModel.id, auto_route: autoRoute };
      const response = await fetch(`/api${path}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      await consumeSse(
        response,
        (event: StreamEvent) => {
          if (event.type === "start" && event.message_id) {
            queryClient.setQueryData<Message[]>(
              ["messages", token, conversationId],
              (existing = []) => [
                ...existing,
                {
                  ...initialMessage(event.message_id!, "assistant", ""),
                  model_id: event.model_id ?? null,
                  status: "streaming",
                },
              ],
            );
          } else if (event.type === "token" && event.message_id) {
            updateMessage(conversationId, event.message_id, (message) => ({
              ...message,
              content: message.content + (event.text ?? ""),
            }));
          } else if (event.type === "complete" && event.message_id) {
            updateMessage(conversationId, event.message_id, (message) => ({
              ...message,
              status: "complete",
              input_tokens: event.input_tokens ?? 0,
              output_tokens: event.output_tokens ?? 0,
              latency_ms: event.latency_ms ?? null,
              estimated_cost_usd: event.estimated_cost_usd ?? 0,
            }));
          } else if (event.type === "error") {
            setStreamError(event.message ?? "This model could not complete the request.");
            if (event.message_id) {
              updateMessage(conversationId, event.message_id, (message) => ({
                ...message,
                status: "failed",
              }));
            }
          } else if (event.type === "retry") {
            setToast(event.message ?? "Retrying with another model…");
          }
        },
        controller.signal,
      );
    } catch (error) {
      if (!controller.signal.aborted) {
        setStreamError(error instanceof Error ? error.message : "The model stream was interrupted.");
        queryClient.setQueryData<Message[]>(
          ["messages", token, conversationId],
          (existing = []) =>
            existing.filter((message) => message.id !== temporaryUser.id),
        );
      }
    } finally {
      setStreaming(false);
      abortController.current = null;
      await refreshConversationData(conversationId);
    }
  };

  const submitPrompt = async (mode: "chat" | "compare" = view === "compare" ? "compare" : "chat") => {
    const content = prompt.trim();
    if (!content || streaming) return;
    if (mode === "chat" && (!selectedModel?.available || !selectedModel.enabled)) {
      setStreamError("No model is available. Configure a provider key in the backend environment.");
      return;
    }
    if (mode === "compare" && effectiveCompareModelIds.length < 2) {
      setStreamError("Choose at least two models to compare.");
      return;
    }
    setPrompt("");
    setStreamError("");
    try {
      const conversation =
        activeConversation ??
        (await createConversation(mode === "compare" ? "compare" : "chat"));
      await streamRequest(conversation.id, content, mode);
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : "Could not start the conversation.");
      setPrompt(content);
    }
  };

  const onComposerKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      void submitPrompt();
    }
  };

  const newConversation = async () => {
    setStreamError("");
    try {
      await createConversation(view === "compare" ? "compare" : "chat");
      if (view === "usage") setView("chat");
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : "Unable to create a conversation.");
    }
  };

  const copyText = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setToast("Copied to clipboard");
    } catch {
      setStreamError("Clipboard access is unavailable in this browser.");
    }
  };

  const exportConversation = async () => {
    if (!activeConversation) return;
    try {
      const document = await api<Record<string, unknown>>(
        `/conversations/${activeConversation.id}/export`,
      );
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(document, null, 2)], { type: "application/json" }),
      );
      const link = window.document.createElement("a");
      link.href = url;
      link.download = `${activeConversation.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : "Export failed.");
    }
  };

  const renameConversation = async (conversation: Conversation) => {
    const title = window.prompt("Rename conversation", conversation.title)?.trim();
    if (!title || title === conversation.title) return;
    try {
      await api(`/conversations/${conversation.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      });
      await queryClient.invalidateQueries({ queryKey: ["conversations", token] });
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : "Rename failed.");
    }
  };

  const deleteConversation = async (conversation: Conversation) => {
    if (!window.confirm(`Delete “${conversation.title}” and its messages?`)) return;
    try {
      await api(`/conversations/${conversation.id}`, { method: "DELETE" });
      if (activeConversationId === conversation.id) setSelectedConversationId("");
      await queryClient.invalidateQueries({ queryKey: ["conversations", token] });
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : "Delete failed.");
    }
  };

  const giveFeedback = async (messageId: string, rating: -1 | 1) => {
    try {
      await api(`/messages/${messageId}/feedback`, {
        method: "POST",
        body: JSON.stringify({ rating }),
      });
      setToast("Thanks for the feedback");
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : "Feedback could not be saved.");
    }
  };

  const saveBudget = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      const updated = await api<Workspace>("/auth/workspace", {
        method: "PATCH",
        body: JSON.stringify({
          monthly_budget_usd: budgetDraft === "" ? null : Number(budgetDraft),
        }),
      });
      queryClient.setQueryData(["workspace", token], updated);
      setBudgetSaved(true);
      window.setTimeout(() => setBudgetSaved(false), 1800);
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : "Budget limit could not be updated.");
    }
  };

  const saveModelPermissions = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      const updated = await api<Workspace>("/auth/workspace", {
        method: "PATCH",
        body: JSON.stringify({ allowed_model_ids: allowedModelIds }),
      });
      queryClient.setQueryData(["workspace", token], updated);
      setModelPermissionDraft(undefined);
      setToast("Workspace model access saved");
      await queryClient.invalidateQueries({ queryKey: ["models", token] });
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : "Model permissions could not be saved.");
    }
  };

  const chooseCompareModel = (modelId: string, selected: boolean) => {
    if (selected) {
      setCompareModelIds((current) => {
        const selection = current.length ? current : effectiveCompareModelIds;
        return selection.length < 4 ? [...selection, modelId] : selection;
      });
      return;
    }
    setCompareModelIds((current) =>
      (current.length ? current : effectiveCompareModelIds).filter((id) => id !== modelId),
    );
  };

  if (!tokenReady) return <div className="loading-state">Loading Modelspace…</div>;

  if (!token || userQuery.isError) {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <Link className="brand" href="/">
            <span className="brand-mark"><Command size={16} /></span>
            <span className="brand-word">model<span>space</span></span>
          </Link>
          <p className="eyebrow">A calmer way to work with AI</p>
          <h1>{authMode === "login" ? "Welcome back" : "Create your workspace"}</h1>
          <p className="auth-copy">
            One conversation space for the models, tools, and ideas you rely on.
          </p>
          {userQuery.isError && <div className="notice">Your session has ended. Sign in again to continue.</div>}
          {authError && <div className="auth-error" role="alert">{authError}</div>}
          <form className="auth-form" onSubmit={beginAuth}>
            {authMode === "register" && (
              <>
                <label className="auth-field">Your name
                  <input required minLength={1} maxLength={100} autoComplete="name" value={authForm.display_name} onChange={(event) => setAuthForm({ ...authForm, display_name: event.target.value })} placeholder="e.g. Jordan Lee" />
                </label>
                <label className="auth-field">Workspace name
                  <input required minLength={1} maxLength={100} value={authForm.workspace_name} onChange={(event) => setAuthForm({ ...authForm, workspace_name: event.target.value })} placeholder="e.g. Studio North" />
                </label>
              </>
            )}
            <label className="auth-field">Email address
              <input required type="email" autoComplete="email" maxLength={320} value={authForm.email} onChange={(event) => setAuthForm({ ...authForm, email: event.target.value })} placeholder="you@company.com" />
            </label>
            <label className="auth-field">Password
              <input required type="password" minLength={authMode === "register" ? 12 : 1} maxLength={128} autoComplete={authMode === "login" ? "current-password" : "new-password"} value={authForm.password} onChange={(event) => setAuthForm({ ...authForm, password: event.target.value })} placeholder={authMode === "login" ? "Your password" : "At least 12 characters"} />
            </label>
            <Button className="button primary" type="submit" disabled={authBusy}>
              {authBusy ? "Please wait…" : authMode === "login" ? "Sign in" : "Create workspace"}
              <ArrowUp size={14} />
            </Button>
          </form>
          <p className="auth-switch">
            {authMode === "login" ? "New to Modelspace?" : "Already have an account?"}
            <button type="button" onClick={() => { setAuthError(""); setAuthMode(authMode === "login" ? "register" : "login"); }}>
              {authMode === "login" ? "Create a workspace" : "Sign in"}
            </button>
          </p>
        </section>
      </main>
    );
  }

  if (userQuery.isLoading || !user) {
    return <div className="loading-state">Loading your workspace…</div>;
  }

  const activeResponses = compareResponses;
  const submitLabel = view === "compare" ? "Compare models" : "Send message";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" href="/" aria-label="Modelspace home">
          <span className="brand-mark"><Command size={16} /></span>
          <span className="brand-word">model<span>space</span></span>
        </Link>
        <div className="workspace-pill">
          <span className="workspace-avatar">{workspace?.name.slice(0, 1).toUpperCase() ?? "M"}</span>
          <span className="workspace-meta"><strong>{workspace?.name ?? "My workspace"}</strong><small>{workspace?.role ?? "Workspace"} workspace</small></span>
          <ChevronDown size={14} color="#858c82" />
        </div>
        <p className="sidebar-label">Workspace</p>
        <nav className="nav-list" aria-label="Workspace navigation">
          <button className={`nav-item${view === "chat" ? " active" : ""}`} type="button" onClick={() => setView("chat")}><MessageSquare /> Chat <span className="nav-end">⌘1</span></button>
          <button className={`nav-item${view === "compare" ? " active" : ""}`} type="button" onClick={() => setView("compare")}><ArrowLeftRight /> Compare <span className="nav-end">⌘2</span></button>
          <button className={`nav-item${view === "usage" ? " active" : ""}`} type="button" onClick={() => setView("usage")}><BarChart3 /> Usage <span className="nav-end">⌘3</span></button>
        </nav>
        <button className="new-chat" type="button" onClick={() => void newConversation()}><Plus size={15} /> New conversation <span className="nav-end">⌘N</span></button>
        <div className="sidebar-label" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span>Recent conversations</span>
          <Search size={13} />
        </div>
        <input className="small-select" aria-label="Search conversations" placeholder="Find a conversation…" value={conversationSearch} onChange={(event) => setConversationSearch(event.target.value)} />
        <div className="conversation-list">
          {conversationsQuery.isLoading && <div className="conversation-empty">Loading conversations…</div>}
          {filteredConversations.map((conversation) => (
            <div key={conversation.id} style={{ position: "relative" }}>
              <button className={`conversation-item${activeConversationId === conversation.id ? " active" : ""}`} type="button" onClick={() => { setSelectedConversationId(conversation.id); setView(conversation.mode === "compare" ? "compare" : "chat"); }}>
                <MessageSquare size={13} /><span>{conversation.title}</span>
              </button>
              {activeConversationId === conversation.id && <button className="icon-button" style={{ position: "absolute", right: 2, top: 2, width: 25, height: 27 }} type="button" aria-label={`Conversation actions for ${conversation.title}`} title="Rename or delete conversation" onClick={(event) => { event.stopPropagation(); const action = window.prompt("Type rename or delete", "rename"); if (action?.toLowerCase() === "delete") void deleteConversation(conversation); else if (action?.toLowerCase() === "rename") void renameConversation(conversation); }}><MoreHorizontal size={14} /></button>}
            </div>
          ))}
          {!conversationsQuery.isLoading && filteredConversations.length === 0 && <div className="conversation-empty">{conversationSearch ? "No conversations match." : "Start a chat to make your first conversation."}</div>}
        </div>
        <div className="sidebar-bottom">
          <div className="provider-status">
            <span className={`status-dot${availableModels.length ? "" : " offline"}`} />
            {modelsQuery.isLoading ? "Checking model providers…" : availableModels.length ? `${availableModels.length} models ready` : "Provider keys needed"}
            <span className="nav-end"><Settings2 size={13} /></span>
          </div>
          <div className="profile-menu">
            <span className="profile-avatar">{user.display_name.slice(0, 2).toUpperCase()}</span>
            <span className="profile-copy"><strong>{user.display_name}</strong><small>{user.email}</small></span>
            <button className="icon-button" type="button" title="Sign out" aria-label="Sign out" onClick={signOut}><LogOut size={15} /></button>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><span>/</span><strong>{view === "chat" ? activeConversation?.title ?? "New conversation" : view === "compare" ? "Model comparison" : "Usage overview"}</strong></div>
          <div className="topbar-actions">
            {activeConversation && view !== "usage" && <button className="icon-button" type="button" title="Export conversation" aria-label="Export conversation" onClick={() => void exportConversation()}><ArrowDownToLine size={15} /></button>}
            <span className="keyboard-hint">Command palette <span className="keycap">⌘ K</span></span>
            <button className="icon-button" type="button" title="Help" aria-label="Help"><CircleHelp size={15} /></button>
          </div>
        </header>

        <main className="page-main">
          {streamError && <div className="error-banner" role="alert">{streamError}<button type="button" className="icon-button" style={{ float: "right", width: 20, height: 20 }} aria-label="Dismiss error" onClick={() => setStreamError("")}>×</button></div>}
          {modelsQuery.isError && <div className="notice">Could not load models. Check the API service and reload.</div>}
          {view === "chat" && (
            <>
              <div className="page-heading">
                <div><p className="eyebrow">Your AI command center</p><h1>{activeConversation?.title ?? "What are we thinking?"}</h1><p>One calm place for every question, model, and half-formed idea.</p></div>
                <div className="segmented" role="tablist" aria-label="Conversation mode"><button className="segment active" type="button" role="tab" aria-selected="true"><MessageSquare size={13} /> Chat</button><button className="segment" type="button" role="tab" aria-selected="false" onClick={() => setView("compare")}><ArrowLeftRight size={13} /> Compare</button></div>
              </div>
              <section className="chat-layout">
                <div className="chat-panel">
                  <div className="chat-panel-top">
                    <div className="selected-model">
                      <span className="model-glyph"><Sparkles size={14} /></span>
                      <select aria-label="Choose a model" className="model-select" value={selectedModel?.id ?? ""} onChange={(event) => setSelectedModelId(event.target.value)} disabled={!models.length}>
                        {models.map((model) => <option key={model.id} value={model.id} disabled={!model.available || !model.enabled}>{model.label}{!model.available ? " · add API key" : !model.enabled ? " · workspace disabled" : ""}</option>)}
                      </select>
                      <span className="model-subtitle">{selectedModel?.provider_id ?? "No provider"}</span>
                    </div>
                    <div className="chat-toolbar"><button className="icon-button" type="button" title="Model settings" aria-label="Model settings"><Settings2 size={15} /></button><button className="icon-button" type="button" title="Conversation options" aria-label="Conversation options"><MoreHorizontal size={16} /></button></div>
                  </div>
                  <div className="messages" aria-live="polite">
                    {messagesQuery.isLoading && activeConversationId && <div className="conversation-empty">Loading conversation…</div>}
                    {!messages.length && !messagesQuery.isLoading && <div className="welcome-state"><span className="welcome-symbol"><Sparkles size={22} /></span><h2>A good question goes a long way.</h2><p>Choose a model, share what is on your mind, and build on the answer together.</p><div className="prompt-suggestions">{starterPrompts.map((suggestion) => <button className="prompt-suggestion" type="button" key={suggestion} onClick={() => setPrompt(suggestion)}>{suggestion}</button>)}</div></div>}
                    {messages.map((message, index) => message.role === "user" ? (
                      <div className="message-row user" key={message.id}><div className="message-content">{message.content}</div></div>
                    ) : (
                      <div className="message-row" key={message.id}>
                        <span className="message-avatar"><Sparkles size={13} /></span>
                        <div className="message-content">
                          <div className="message-author">{models.find((model) => model.id === message.model_id)?.label ?? "Modelspace"} <small>{message.status === "streaming" ? "responding" : message.status}</small></div>
                          {message.content ? <div className="message-text">{message.content}</div> : message.status === "streaming" ? <div className="typing-dots"><i /><i /><i /></div> : <div className="message-text">{message.status === "failed" ? "This response did not complete." : "Generation stopped."}</div>}
                          <div className="message-meta">
                            {message.status === "complete" && <><span>{message.latency_ms ? `${(message.latency_ms / 1000).toFixed(1)}s` : "Complete"}</span><span>{formatCount(message.input_tokens + message.output_tokens)} tokens</span><span>{formatCurrency(message.estimated_cost_usd)}</span></>}
                            <span className="message-tools">
                              <button type="button" aria-label="Copy response" title="Copy response" onClick={() => void copyText(message.content)}><Copy size={12} /></button>
                              {message.status === "complete" && <><button type="button" aria-label="Good response" title="Good response" onClick={() => void giveFeedback(message.id, 1)}><ThumbsUp size={12} /></button><button type="button" aria-label="Poor response" title="Poor response" onClick={() => void giveFeedback(message.id, -1)}><ThumbsDown size={12} /></button></>}
                              {message.status === "failed" && <button type="button" aria-label="Retry response" title="Retry response" onClick={() => { const previous = messages.slice(0, index).reverse().find((item) => item.role === "user"); if (previous) { setPrompt(previous.content); void streamRequest(activeConversationId, previous.content, "chat"); } }}><RefreshCw size={12} /></button>}
                            </span>
                          </div>
                        </div>
                      </div>
                    ))}
                    <div ref={messagesEnd} />
                  </div>
                  <div className="composer-wrap">
                    <div className="composer-box">
                      <textarea aria-label="Write your message" placeholder={selectedModel?.available && selectedModel.enabled ? "Ask anything, draft something, or think out loud…" : selectedModel?.available ? "Ask an owner to enable this model for your workspace…" : "Add a provider API key to begin generating responses…"} value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={onComposerKey} disabled={!selectedModel?.available || !selectedModel.enabled || streaming} />
                      <div className="composer-controls"><span className="composer-hint"><KeyRound size={11} /> ⌘ Enter to send <span>·</span> {prompt.length.toLocaleString()} / 50,000</span><div className="composer-actions"><select aria-label="Response length"><option>Balanced</option><option>Concise</option><option>Detailed</option></select>{streaming ? <button className="send-button" type="button" aria-label="Stop generation" title="Stop generation" onClick={() => abortController.current?.abort()}><StopCircle size={15} /></button> : <button className="send-button" type="button" aria-label={submitLabel} title={submitLabel} disabled={!prompt.trim() || !selectedModel?.available || !selectedModel.enabled} onClick={() => void submitPrompt("chat")}><Send size={15} /></button>}</div></div>
                    </div>
                  </div>
                </div>
                <aside className="context-panel">
                  <div className="context-heading">Model details <MoreHorizontal size={15} /></div>
                  <div className="context-card"><h3>Selected model</h3><p>{selectedModel?.description ?? "Choose a configured model to see its strengths."}</p></div>
                  <div className="context-card"><h3>Model library</h3>{models.map((model) => <div className="model-option" key={model.id}><span className="model-glyph" style={{ width: 23, height: 23 }}><Zap size={12} /></span><span><strong>{model.label}</strong><small>{model.provider_id}</small></span><em>{!model.available ? "API key" : model.enabled ? "Ready" : "Restricted"}</em></div>)}{!models.length && <p>Model catalog is loading.</p>}</div>
                  <div className="context-card"><h3>Smart routing</h3><p>Automatically retry a suitable fallback model if your selected provider is unavailable.</p><label className="routing-toggle"><input type="checkbox" checked={autoRoute} onChange={(event) => setAutoRoute(event.target.checked)} /><span>Enable provider fallback</span></label></div>
                  <div className="context-footer">Model responses can be inaccurate. Review important decisions and avoid sharing sensitive information.</div>
                </aside>
              </section>
            </>
          )}

          {view === "compare" && (
            <>
              <div className="page-heading"><div><p className="eyebrow">Side-by-side evaluation</p><h1>Let the models make their case.</h1><p>Ask once, compare approaches, and choose the response that moves you forward.</p></div><div className="segmented"><button className="segment" type="button" onClick={() => setView("chat")}><MessageSquare size={13} /> Chat</button><button className="segment active" type="button"><ArrowLeftRight size={13} /> Compare</button></div></div>
              <section className="dashboard-card" style={{ marginBottom: 14 }}>
                <div className="context-heading" style={{ marginBottom: 10 }}>Models to compare <span style={{ color: "#9aa095", fontSize: 8 }}>Choose 2–4</span></div>
                <div className="compare-model-choices">{models.map((model) => <label className="compare-choice" key={model.id}><input type="checkbox" checked={effectiveCompareModelIds.includes(model.id)} disabled={!model.available || !model.enabled || (!effectiveCompareModelIds.includes(model.id) && effectiveCompareModelIds.length >= 4)} onChange={(event) => chooseCompareModel(model.id, event.target.checked)} /><span>{model.label}</span><small>{!model.available ? "API key needed" : model.enabled ? model.provider_id : "Workspace disabled"}</small></label>)}</div>
                <div className="compare-prompt"><textarea aria-label="Question for model comparison" placeholder="Write one question for every model…" value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={onComposerKey} /><button className="button primary" type="button" disabled={streaming || !prompt.trim() || effectiveCompareModelIds.filter((id) => models.some((model) => model.id === id && model.available && model.enabled)).length < 2} onClick={() => void submitPrompt("compare")}><ArrowLeftRight size={14} /> Compare answers</button></div>
                {streaming && <button className="button" type="button" onClick={() => abortController.current?.abort()}><StopCircle size={13} /> Stop comparison</button>}
              </section>
              <section className="compare-grid" aria-label="Model responses">
                {effectiveCompareModelIds.length ? effectiveCompareModelIds.map((modelId) => {
                  const model = models.find((item) => item.id === modelId);
                  const response = activeResponses.find((item) => item.model_id === modelId);
                  return <article className="compare-card" key={modelId}><header className="compare-card-header"><span className="selected-model"><span className="model-glyph"><Sparkles size={13} /></span><strong>{model?.label ?? modelId}</strong></span><small style={{ color: "#999f96", fontSize: 8 }}>{response?.latency_ms ? `${(response.latency_ms / 1000).toFixed(1)}s` : response?.status ?? "Ready"}</small></header><div className="compare-body">{response?.content || (response?.status === "streaming" ? "Generating…" : response?.status === "failed" ? "This model could not complete the request." : "Send a question to compare responses.")}</div>{response?.status === "complete" && <footer className="message-meta" style={{ padding: "0 13px 11px" }}><span>{formatCount(response.input_tokens + response.output_tokens)} tokens</span><span>{formatCurrency(response.estimated_cost_usd)}</span><span className="message-tools"><button type="button" aria-label="Copy response" onClick={() => void copyText(response.content)}><Copy size={12} /></button><button type="button" aria-label="Good response" onClick={() => void giveFeedback(response.id, 1)}><ThumbsUp size={12} /></button><button type="button" aria-label="Poor response" onClick={() => void giveFeedback(response.id, -1)}><ThumbsDown size={12} /></button></span></footer>}</article>;
                }) : <div className="compare-card"><div className="compare-empty">Configure at least two providers to compare models.</div></div>}
              </section>
            </>
          )}

          {view === "usage" && (
            <>
              <div className="page-heading"><div><p className="eyebrow">Workspace insights</p><h1>Usage, at a glance.</h1><p>Understand where your tokens, time, and estimated model spend are going.</p></div><button className="button" type="button" onClick={() => void usageQuery.refetch()}><RefreshCw size={13} /> Refresh</button></div>
              {usageQuery.isLoading ? <div className="empty-dashboard">Loading usage…</div> : usageQuery.isError ? <div className="notice">Usage metrics could not be loaded.</div> : (
                <>
                  <div className="dashboard-grid">
                    <article className="dashboard-card"><div className="metric-label"><Activity size={14} /> Total requests</div><div className="metric-value">{formatCount(usageQuery.data?.requests ?? 0)}</div><div className="metric-footnote">{usageQuery.data?.failed_requests ?? 0} failed requests</div></article>
                    <article className="dashboard-card"><div className="metric-label"><Workflow size={14} /> Tokens consumed</div><div className="metric-value">{formatCount((usageQuery.data?.input_tokens ?? 0) + (usageQuery.data?.output_tokens ?? 0))}</div><div className="metric-footnote">{formatCount(usageQuery.data?.input_tokens ?? 0)} input · {formatCount(usageQuery.data?.output_tokens ?? 0)} output</div></article>
                    <article className="dashboard-card"><div className="metric-label"><Gauge size={14} /> Estimated spend</div><div className="metric-value">{formatCurrency(usageQuery.data?.estimated_cost_usd ?? 0)}</div><div className="metric-footnote">Estimated from configured per-model rates</div></article>
                    <article className="dashboard-card"><div className="metric-label"><Clock3 size={14} /> Avg. latency</div><div className="metric-value">{((usageQuery.data?.average_latency_ms ?? 0) / 1000).toFixed(1)}s</div><div className="metric-footnote">Across completed and failed runs</div></article>
                  </div>
                  <section className="dashboard-card" style={{ marginBottom: 14 }}>
                    <div className="context-heading" style={{ marginBottom: 10 }}>Workspace spending limit <span style={{ color: "#939a8f", fontSize: 8 }}>{workspace?.role ?? "member"} access</span></div>
                    <form className="budget-form" onSubmit={saveBudget}><label>Monthly limit in USD<input type="number" min="0" max="1000000" step="0.01" disabled={!["owner", "admin"].includes(workspace?.role ?? "")} placeholder={workspace?.monthly_budget_usd?.toString() ?? "No limit"} value={budgetDraft} onChange={(event) => setBudgetDraft(event.target.value)} /></label><button className="button" type="submit" disabled={!["owner", "admin"].includes(workspace?.role ?? "")}>{budgetSaved ? <Check size={13} /> : <Settings2 size={13} />}{budgetSaved ? "Saved" : "Save limit"}</button></form>
                    <p className="metric-footnote" style={{ marginTop: 8 }}>New generations pause once recorded successful usage reaches this limit.</p>
                  </section>
                  <section className="dashboard-card" style={{ marginBottom: 14 }}>
                    <div className="context-heading" style={{ marginBottom: 10 }}>Workspace model access <span style={{ color: "#939a8f", fontSize: 8 }}>{workspace?.allowed_model_ids ? "Restricted" : "All models enabled"}</span></div>
                    <form onSubmit={saveModelPermissions}>
                      <div className="compare-model-choices">{models.map((model) => <label className="compare-choice" key={model.id}><input type="checkbox" checked={allowedModelIds.includes(model.id)} disabled={!["owner", "admin"].includes(workspace?.role ?? "")} onChange={(event) => { const current = allowedModelIds; setModelPermissionDraft(event.target.checked ? [...new Set([...current, model.id])] : current.filter((id) => id !== model.id)); }} /><span>{model.label}</span><small>{model.provider_id}</small></label>)}</div>
                      <button className="button" type="submit" disabled={!["owner", "admin"].includes(workspace?.role ?? "")}><Settings2 size={13} /> Save model access</button>
                    </form>
                    <p className="metric-footnote" style={{ marginTop: 8 }}>Owners and admins can limit which configured models members may use. Provider API keys stay on the backend.</p>
                  </section>
                  <section className="dashboard-card"><div className="context-heading" style={{ marginBottom: 8 }}>Model breakdown</div>{usageQuery.data?.by_model.length ? <div style={{ overflowX: "auto" }}><table className="usage-table"><thead><tr><th>MODEL</th><th>REQUESTS</th><th>TOKENS</th><th>AVG. LATENCY</th><th>FAILED</th><th>EST. SPEND</th></tr></thead><tbody>{usageQuery.data.by_model.map((row) => <tr key={row.model_id}><td className="table-model"><span className="model-glyph" style={{ width: 23, height: 23 }}><Sparkles size={11} /></span>{row.label}</td><td>{formatCount(row.requests)}</td><td>{formatCount(row.input_tokens + row.output_tokens)}</td><td>{(row.average_latency_ms / 1000).toFixed(1)}s</td><td>{row.failed_requests}</td><td>{formatCurrency(row.estimated_cost_usd)}</td></tr>)}</tbody></table></div> : <div className="empty-dashboard">Usage will appear after your first model response.</div>}</section>
                </>
              )}
            </>
          )}
        </main>
      </div>
      {toast && <div role="status" style={{ position: "fixed", right: 20, bottom: 20, zIndex: 10, padding: "10px 13px", border: "1px solid var(--line)", borderRadius: 7, background: "white", color: "#586451", boxShadow: "var(--shadow)", fontSize: 10 }}>{toast}</div>}
    </div>
  );
}
