import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import "./styles.css";

import Overview from "./pages/Overview";
import Attention from "./pages/Attention";
import Customers from "./pages/Customers";
import CustomerDetail from "./pages/CustomerDetail";
import CallView from "./pages/CallView";
import Agents from "./pages/Agents";
import Trends from "./pages/Trends";
import Quality from "./pages/Quality";
import QA from "./pages/QA";

function Shell() {
  const link = ({ isActive }) => (isActive ? "active" : "");
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-dot" />
          <div>
            <h1>CallRadar</h1>
            <span>Conversation Intelligence</span>
          </div>
        </div>
        <nav className="nav">
          <NavLink to="/" end className={link}><span className="nav-ico">◎</span> Overview</NavLink>
          <NavLink to="/attention" className={link}><span className="nav-ico">▲</span> Needs Attention</NavLink>
          <NavLink to="/qa" className={link}><span className="nav-ico">◈</span> QA & Compliance</NavLink>
          <NavLink to="/customers" className={link}><span className="nav-ico">◍</span> Customers</NavLink>
          <NavLink to="/agents" className={link}><span className="nav-ico">◆</span> Agents</NavLink>
          <NavLink to="/trends" className={link}><span className="nav-ico">≈</span> Trends</NavLink>
          <NavLink to="/quality" className={link}><span className="nav-ico">✓</span> Quality</NavLink>
        </nav>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/attention" element={<Attention />} />
          <Route path="/customers" element={<Customers />} />
          <Route path="/customers/:name" element={<CustomerDetail />} />
          <Route path="/calls/:sid" element={<CallView />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/trends" element={<Trends />} />
          <Route path="/quality" element={<Quality />} />
          <Route path="/qa" element={<QA />} />
        </Routes>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </React.StrictMode>
);
