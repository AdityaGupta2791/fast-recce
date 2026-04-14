import { Routes, Route } from "react-router-dom";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<PlaceholderHome />} />
    </Routes>
  );
}

function PlaceholderHome() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <div className="text-center">
        <h1 className="text-3xl font-bold">FastRecce</h1>
        <p className="mt-2 text-muted-foreground">Location Acquisition OS — scaffolding ready</p>
      </div>
    </div>
  );
}
