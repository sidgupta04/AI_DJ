import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/600.css";
import "@fontsource/manrope/800.css";
import "./style.css";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(<App />);
