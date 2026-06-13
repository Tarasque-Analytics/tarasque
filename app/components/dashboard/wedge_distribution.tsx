import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from "chart.js";
import { useMemo, useState } from "react";
import { Line } from "react-chartjs-2";
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
);

const WEDGE = true;
const RETURNS = false;

const SECTOR = 0;
const SUBSECTOR = 1;
const MKTSUBSECTOR = 2;
const MARKET = 3;

const X_AXIS = Array.from({ length: 101 }, (_, i) => i);

export default function WedgeDistribution() {
  const [distType, setDistType] = useState(WEDGE);// by default pick wedge
  const [distClass, setDistClass] = useState(SECTOR);// by default pick sector
  
  const data = useMemo(() => {
    if (distClass === SECTOR) {
      return getSector(distType);
    } else if (distClass === SUBSECTOR) {
      return getSubSector(distType);
    } else if (distClass === MKTSUBSECTOR) {
      return getMktSector(distType);
    } else {
      return getMarket(distType);
    }
  }, [distType, distClass]);

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
      },
      title: {
        display: false,
      },
    },
    scales: {
      y: {
        beginAtZero: false,
        ticks: {
          font: { size: 10 },
        },
      },
      x: {
        ticks: {
          font: { size: 10 },
          stepSize: 10,
          maxTicksLimit: 11,
          callback: function(value: string | number, index: number) {
            if (typeof value === 'number' && value % 10 === 0) {
              return value;
            }
            return '';
          }, // Show only every 10th label 
        },
      },
    },
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Line data={data} options={options} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="col-start-1 col-span-1 p-2 flex flex-col">
          <p>Distribution Type:</p>
          <button className="wedge_dist_button" onClick={() => setDistType(WEDGE)}>Wedge</button>
          <button className="wedge_dist_button" onClick={() => setDistType(RETURNS)}>Returns</button>
        </div>
        <div className="col-start-2 col-span-1 p-2 flex flex-col">
          <p>Distribution Class:</p>
          <button className="wedge_dist_button" onClick={() => setDistClass(SECTOR)}>Sector</button>  
          <button className="wedge_dist_button" onClick={() => setDistClass(SUBSECTOR)}>Sub-Sector</button>
          <button className="wedge_dist_button" onClick={() => setDistClass(MKTSUBSECTOR)}>Mkt Sub-Sector</button>
          <button className="wedge_dist_button" onClick={() => setDistClass(MARKET)}>Market</button>
        </div>
      </div>
    </div>
  );
}


// Gamma function approximation (Lanczos approximation)
function gammaFunction(z: number): number {
  const g = 7;
  const coef = [
    0.99999999999980993,
    676.5203681218851,
    -1259.1392167224028,
    771.32342877765313,
    -176.61502916214059,
    12.507343278686905,
    -0.13857109526572012,
    9.9843695780195716e-6,
    1.5056327351493116e-7
  ];
  
  if (z < 0.5) {
    return Math.PI / (Math.sin(Math.PI * z) * gammaFunction(1 - z));
  }
  
  z -= 1;
  let x = coef[0];
  for (let i = 1; i < g + 2; i++) {
    x += coef[i] / (z + i);
  }
  
  const t = z + g + 0.5;
  return Math.sqrt(2 * Math.PI) * Math.pow(t, z + 0.5) * Math.exp(-t) * x;
}

// TEMPORARY ONLY FOR DEMO 
function gammaDistribution(x: number, shape: number, scale: number) {
  if (x <= 0) return 0;
  const numerator = Math.pow(x, shape - 1) * Math.exp(-x / scale);
  const denominator = Math.pow(scale, shape) * gammaFunction(shape);
  return numerator / denominator;
}

// TEMPORARY ONLY FOR DEMO 
function normalDistribution(x: number, mean: number, stdev: number) {
  const numerator = Math.exp(-((x - mean) ** 2) / (2 * stdev ** 2));
  const denominator = stdev * Math.sqrt(2 * Math.PI);
  return numerator / denominator;
}

function getSector(disType: boolean) {
  console.log("Sector")
  let data = null;
  if (disType === WEDGE) {  
    data = X_AXIS.map(x => normalDistribution(x, 50, 15) * 100); // TODO: replace with real wedge distribution once model and database are set up
  } else {
    data = X_AXIS.map(x => gammaDistribution(x, 2, 15) * 100); // TODO: replace with real gamma distribution once model and database are set up
  }
  return {
      labels: X_AXIS,
      datasets: [
        {
          label: "Sector",
          data: data,
          borderColor: "#36A2EB",
          backgroundColor: "rgba(54, 162, 235, 0.1)",
          borderWidth: 2,
          fill: true,
          tension: 0.4,
          pointRadius: 0
        },
      ],
    };
}

function getSubSector(disType: boolean) {
  console.log("Sub-Sector")
  let data = null;
  if (disType === WEDGE) {  
    data = X_AXIS.map(x => normalDistribution(x, 50, 15) * 100); // TODO: replace with real wedge distribution once model and database are set up
  } else {
    data = X_AXIS.map(x => gammaDistribution(x, 2, 15) * 100); // TODO: replace with real wedge distribution once model and database are set up
  }
  return {
      labels: X_AXIS,
      datasets: [
        {
          label: "Sub-Sector",
          data: data,
          borderColor: "#36A2EB",
          backgroundColor: "rgba(54, 162, 235, 0.1)",
          borderWidth: 2,
          fill: true,
          tension: 0.4,
          pointRadius: 0
        },
      ],
    };
}

function getMktSector(disType: boolean) {
  console.log("Mkt Sub-Sector")
  let data = null;
  if (disType === WEDGE) {  
    data = X_AXIS.map(x => normalDistribution(x, 50, 15) * 100); // TODO: replace with real wedge distribution once model and database are set up
  } else {
    data = X_AXIS.map(x => gammaDistribution(x, 2, 15) * 100); // TODO: replace with real wedge distribution once model and database are set up
  }
  return {
      labels: X_AXIS,
      datasets: [
        {
          label: "Mkt Sub-Sector",
          data: data,
          borderColor: "#36A2EB",
          backgroundColor: "rgba(54, 162, 235, 0.1)",
          borderWidth: 2,
          fill: true,
          tension: 0.4,
          pointRadius: 0
        },
      ],
    };
}

function getMarket(disType: boolean) {
  console.log("Market")
  let data = null;
  if (disType === WEDGE) {  
    data = X_AXIS.map(x => normalDistribution(x, 50, 15) * 100); // TODO: replace with real wedge distribution once model and database are set up
  } else {
    data = X_AXIS.map(x => gammaDistribution(x, 2, 15) * 100); // TODO: replace with real wedge distribution once model and database are set up
  }
  return {
      labels: X_AXIS,
      datasets: [
        {
          label: "Market",
          data: data,
          borderColor: "#36A2EB",
          backgroundColor: "rgba(54, 162, 235, 0.1)",
          borderWidth: 2,
          fill: true,
          tension: 0.4,
          pointRadius: 0
        },
      ],
    };
}

