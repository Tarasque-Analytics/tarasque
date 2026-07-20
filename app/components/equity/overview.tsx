import { useState, useEffect } from "react";
import { Card, Empty } from "./section";

export default function Overview() {
    const [message, setMessage] = useState<String>("Loading...");
    useEffect(() => {
        
        const genai = async () => {
        const query = `http://localhost:8000/api/equity/aislop`;
        try {
        const res = await fetch(query);
        const data = await res.json();
        setMessage(data);
        }
    catch(error) {
console.error("fetch failed", error);
    }
    };
        genai();
    },[]);

return (
    <Card>
    <div className = "flex flex-wrap items-start justify-between gap-3">
        <h2 className="text-2xl font-bold tracking-tight text-(--text-primary)">
          AI Overview
        </h2>
        <p>{message}</p>
        <Empty>
            <p>reply</p>
        </Empty>
    </div>
    </Card>
)
}