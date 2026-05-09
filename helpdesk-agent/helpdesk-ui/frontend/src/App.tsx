import { useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { conversations } from "@/lib/conversations";
import { AppHeader } from "./components/AppHeader";
import { ChatPanel } from "./components/ChatPanel";
import { ConversationSidebar } from "./components/ConversationSidebar";
import { TicketInbox } from "./components/TicketInbox";

export function App() {
  // A fresh tab (or refresh) always boots into the empty "New chat"
  // pane. Past conversations are still listed in the sidebar; the
  // user opens one by clicking it. Mirrors ChatGPT/Claude.ai default
  // behaviour and avoids the "why did my new tab open someone
  // else's conversation?" surprise on tab-duplication.
  const [activeId, setActiveId] = useState<string | null>(null);
  const [prefill, setPrefill] = useState("");

  const handleNew = () => {
    const c = conversations.create();
    setActiveId(c.id);
  };

  const referenceTicket = (ticketId: string) => {
    setPrefill(`Take care of ticket ${ticketId}.`);
  };

  return (
    <div className="flex h-full w-full flex-col">
      <AppHeader />
      <Group orientation="horizontal" className="min-h-0 w-full grow">
        <Panel defaultSize="18%" minSize="12%" maxSize="30%" className="h-full">
          <ConversationSidebar activeId={activeId} onSelect={setActiveId} onNew={handleNew} />
        </Panel>
        <ResizeSeparator />
        <Panel defaultSize="54%" minSize="30%" className="h-full">
          <ChatPanel
            activeId={activeId}
            onActiveIdChange={setActiveId}
            prefill={prefill}
            onPrefillConsumed={() => setPrefill("")}
            onPickPrompt={setPrefill}
          />
        </Panel>
        <ResizeSeparator />
        <Panel defaultSize="28%" minSize="18%" maxSize="45%" className="h-full">
          <TicketInbox onReference={referenceTicket} />
        </Panel>
      </Group>
    </div>
  );
}

function ResizeSeparator() {
  // Visually a 1px line, but the element itself is 6px wide so it's
  // actually grabbable. The inner ``::before`` paints the centred line.
  return (
    <Separator className="relative w-1.5 cursor-col-resize bg-transparent before:absolute before:inset-y-0 before:left-1/2 before:w-px before:-translate-x-1/2 before:bg-surface-2 hover:before:bg-emerald-600 focus-visible:before:bg-emerald-500 focus-visible:outline-none">
      <span className="sr-only">Drag to resize</span>
    </Separator>
  );
}
