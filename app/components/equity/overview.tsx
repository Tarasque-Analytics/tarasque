import OpenAI from "openai";
import { useState, useEffect } from "react";
import { Card, Empty } from "./section";
// async function run() {
//     const [ message, setMessage ] = useState<String>('Loading...');

//     const openai = new OpenAI({
//     baseURL: "https://openrouter.ai/api/v1",
//     apiKey: import.meta.env.VITE_llm_api_key,
//     });
//     const completion = await openai.chat.completions.create({
//     model: 'nvidia/nemotron-3-ultra-550b-a55b:free',
//     messages: [
//       {
//         role: 'user',
//         content: 'What is the meaning of life?',
//       }, 
//     ],
//   });
//   setMessage(completion.choices[0].message.content);
//   return (message)
// }

export default function Overview() {
    const [message, setMessage] = useState<String>("Loading...");
const openai = new OpenAI({
baseURL: "https://openrouter.ai/api/v1",
apiKey: import.meta.env.VITE_llm_api_key,
  dangerouslyAllowBrowser: true,

});
const request = `You are a memelord, and have been winning awards for years.
Your task is to translate 朋友是一个坚韧不拔的纪录片， 在香港这座城市的设置。 主演：钱德勒 索罗斯 傅博斯1 瑞秋 莫妮卡 和一些其他他妈的演员。
into a random Romance language, including old languages like Latin.
Only output the translation itself, nothing else, and make sure you only give me one version of the translation.
`
useEffect(() => {
const loadAI = async () => {
    const completion = await openai.chat.completions.create({
  model: "nvidia/nemotron-3-ultra-550b-a55b:free",
  messages: [{ role: "user", content: request }],
});

if (completion.choices[0].message.content) {
    setMessage(completion.choices[0].message.content)
}

}
loadAI();
}, []);
return (
    <Card>
    <div className = "flex flex-wrap items-start justify-between gap-3">
        <p>{message}</p>
        <Empty>
            {/* <p>{reply}</p> */}
        </Empty>
    </div>
    </Card>
)
}