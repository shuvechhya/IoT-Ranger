const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(express.json());

// IMPORTANT: use service name "mongodb"
mongoose.connect('mongodb://mongo:27017/iot_logs');

const Log = mongoose.model('Log', {
  user: String,
  device_id: String,
  status: String,
  timestamp: Date
});

// GET logs (original route)
app.get('/api/logs', async (req, res) => {
    const logs = await Log.find().sort({ timestamp: -1 }).limit(100);
    res.json(logs);
});

// ADD THIS NEW ROUTE FOR GRAFANA
app.get('/metrics', async (req, res) => {
    const logs = await Log.find().sort({ timestamp: -1 }).limit(100);
    res.json(logs);
});

// POST logs
app.post('/api/logs', async (req, res) => {
  const log = new Log(req.body);
  await log.save();
  res.json({ message: "Saved" });
});

app.listen(5000, '0.0.0.0', () => {
  console.log('API running');
});
